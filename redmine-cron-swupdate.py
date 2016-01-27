#!/usr/bin/python

# Requires python-redmine - not in any Debian repository
#     To install python-redmine
#    pypi-install python-redmine
# Creates and installs a debian package python-python-redmine

import sys, os, socket
from datetime import date, datetime
import time
from redmine import Redmine
import re    # Regular Expressions
import getopt
from stat import *
import fcntl
import random

version = '1.0 $Id$'
verbose = 0
noupdate = 0
exit_ok = 0
exit_retry = 75        # See sysexit.h - that's what the Postfix docs refer to
lock_file = '/tmp/redmine-cron-swupdate.lck'
lock_file_fd = -1

redmine_url = 'https://redmine.localdomain'
ssl_checkcert = True
redmine_project = 'software-updates'
api_username='apiuser'
api_password='authfile_is_preferred'
api_authfile=None

##################################################################################
def print_v(msg):
    global verbose
    if verbose:
        print >> sys.stderr, msg
##################################################################################
def usage():
    print "Usage: " + sys.argv[0] + " [-v|-V|-h] [-n | --noupdate] [-u username | --user=username] [-p password| --pass=password] [-k | --sslnocheck]"
    print """
    -v, --verbose  ... print verbose messages
    -n, --noupdate ... dont update the redmine server, just query for an existing ticket
    -s, --server   ... server to connect to. Default is """ + redmine_url + """
    -k, --sslnocheck ... don't check the hostname against the SSL Certificate Common Name
    -u, --user     ... username for logging into API. Default is """ + api_username + """
    -p, --pass     ... password for logging into API. Default is embedded in this script
    -A, --authfile ... read username and password from this file, format is:
                       username=...<nl>password=...<nl>
                         -- or --
                       apikey=...<nl>
    -P, --project  ... Redmine project to create tickets in. Default is """ + redmine_project + """

     Notes:
         A Redmine API key can be used on the command line, specified as the username arg, eg.
               """ + sys.argv[0] + """ -u 1a2b3c4d5e6f -s my-redmine.example.com < mailfile.txt
"""
##################################################################################
def command_args(argv):
    global verbose, noupdate, version, redmine_url, redmine_project, api_username, api_password, api_authfile, ssl_checkcert
    try:
        opts, args = getopt.getopt(argv, 'vVnhks:P:u:p:A:', ['noupdate' ,'verbose', 'version','help','server=','sslnocheck','project=','user=','pass='])
    except getopt.GetoptError:
        usage()
        sys.exit(1)
    try:
        for opt, arg in opts:
            if opt in ('-v', '--verbose'):
                verbose = 1
            elif opt in ('-n', '--noupdate'):
                noupdate = 1
            elif opt in ('-V', '--version'):
                print "redmine-cron-swupdate.py for automatically creating an single daily ticket for cron-apt and cron-yum updates"
                print "Version " + version
                sys.exit(0)
            elif opt in ('-u', '--user'):
                api_username = arg
            elif opt in ('-p', '--pass'):
                api_password = arg
            elif opt in ('-A', '--authfile'):
                api_authfile = arg
            elif opt in ('-P', '--project'):
                redmine_project = arg
            elif opt in ('-s', '--server'):
                if not arg.startswith('http'):
                    arg = 'https://' + arg
                redmine_url = arg
            elif opt in ('-k', '--sslnocheck'):
                ssl_checkcert = False
            elif opt in ('-h', '--help'):
                usage()
                sys.exit(0)
    except SystemExit:
        sys.exit(0)
    except:
        print "Invalid command line arg"
        sys.exit(1)
##################################################################################
def unlock_and_exit(exit_code):
    global lock_file, lock_file_fd
    # Remove the file before reliquishing the lock - safer that way
    os.unlink(lock_file)
    os.close(lock_file_fd)
    sys.exit(exit_code)
##################################################################################
def lock_and_exitonerror():
    global lock_file, lock_file_fd
    # Check and set the lock_file
    # First, see of the lock file is stale (more than 1 hour old) and remove it if so
    lock_file_exists = 0
    old_pid = 0
    try:
        lock_file_stat = os.stat(lock_file)
        lock_file_exists = 1
        lock_file_fd = os.open(lock_file, os.O_RDONLY,0644)
        old_pid = int(os.read(lock_file_fd,20).split()[0])
        os.close(lock_file_fd)
        print_v('Lock file found: %s for PID %d' % (lock_file,old_pid))

    except OSError, oserr:
        print_v('Lock file %s not found - this is good' % lock_file )
    except ValueError:
        print_v('Lock file %s does not contain a PID - lock file will be deleted' % lock_file )
        # Garbage in the PID file - ignore it
        old_pid = 0

    if lock_file_exists:
        if old_pid and lock_file_stat.st_mtime > time.time() - 3600:
            # Lock file exists, AND it is less than 1 hour old
            try:
                os.kill(old_pid, 0)
                print >> sys.stderr, 'Lock file %s: locked by existing process with pid: %d' % (lock_file, old_pid)
                sys.exit(exit_retry)		# Retry email delivery
            except OSError, oserr:
                print_v('No process with pid: %d' % (old_pid) )
        # Lock file exists, but the process does not, or it is over 1 hour old
        try:
            os.unlink(lock_file)
            print_v('Deleted stale lock file: %s' % (lock_file) )
        except OSError, oserr:
            print >> sys.stderr, 'Could not delete stale lock file %s: %s' % (lock_file, sys.exc_info()[1])
            sys.exit(exit_retry)		# Retry email delivery

    # No lock_file found, or stale lock_file removed
    try:
        lock_file_fd = os.open(lock_file, os.O_EXCL|os.O_CREAT|os.O_RDWR,0644)
        os.write(lock_file_fd, str(os.getpid())+"\n" )
        os.fsync(lock_file_fd)
    except OSError, oserr:
        # Includes file already exists
        print >> sys.stderr, 'Cannot open lock file %s: %s' % ( lock_file, sys.exc_info()[0] )
        print >> sys.stderr, '%s: %s' % ( lock_file, sys.exc_info()[1] )
        sys.exit(exit_retry)		# Retry email delivery

    print_v('Created lock_file %s successfully, proceeding...' % (lock_file) )

##################################################################################
def read_authfile():
    global api_username, api_password, api_authfile
    try:
        api_authfile_fh = open(api_authfile,'r')
    except IOError, ioerr:
        print >> sys.stderr, 'Cannot open auth file %s: %s' % ( api_authfile, sys.exc_info()[0] )
        print >> sys.stderr, '%s: %s' % ( api_authfile, sys.exc_info()[1] )
        sys.exit(exit_retry)  # Retry email delivery
    found_username = 0
    found_password = 0
    found_key = 0
    while True:
        try:
            line = api_authfile_fh.readline()
        except IOError, ioerr:
            print >> sys.stderr, 'Cannot read auth file %s: %s' % ( api_authfile, sys.exc_info()[0] )
            break
        line = line.strip()
        if len(line) == 0:
            break
        if line.startswith('#'):
            continue
        kv = line.split('=',2)
        if len(kv) > 0:
            key = kv[0]
        else:
            continue
        if len(kv) > 1:
            value = kv[1]
        else:
            continue
        if key == 'username':
            api_username = value
            found_username = 1
        elif key == 'password':
            api_password = value
            found_password = 1
        elif key == 'apikey':
            api_username = value
            api_password = random.randint(1000001,9999999)
            found_key = 1
        else:
            print >> sys.stderr, 'Unexpected line in auth file - expecting "username" or "password", found "%s"' % key

    api_authfile_fh.close()
    if not found_username and not found_key:
        print >> sys.stderr, 'Warning: Auth file %s did not contain username=...' % api_authfile
    if not found_password and not found_key:
        print >> sys.stderr, 'Warning: Auth file %s did not contain password=...' % api_authfile

    return

##################################################################################
def read_stdin():
    global server_name, notes, action, packages_install, packages_upgrade
    global errors, warnings, updater_is
    #######################################################################
    # Parse the incoming mail message
    #######################################################################
    packages_upg_next = 0
    packages_new_next = 0
    packages_yum_next = 0
    packages_yum_download = 0
    packages_yum_applied = 0
    in_body = 0
    while 1:
        try:
            line = sys.stdin.readline()
        except:
            break
        if not line:
            break

        if not in_body:         # ---------- in e-mail header
            # Common e-mail header parsing
            if line == "\n":
                notes += "\n"
                in_body = 1
            elif line.startswith('Date:') and in_body == 0:
                notes += line
            elif line.startswith('Subject:') and in_body == 0:
                #cronapt subject = 'CRON-APT completed on srv-appx-123 [/etc/cron-apt/config]'
                #cronyum subject = 'Anacron job 'cron.daily' on srv-appx-123'
                print_v(line)
                subj_match = re.search('[Yy]um',line)
                if subj_match != None:
                    updater_is = 'yum'
                subj_match = re.search('(cron.daily.|completed|downloaded|installed)\son\s(\S+)',line)
                if subj_match != None and subj_match.lastindex == 2:
                    server_name = subj_match.group(2)
                    notes = "*%s*\n\n" % server_name + notes
                    print_v(server_name)
                notes += line
        else:                   # ---------- in e-mail body
            # Copy the body of the message into the notes
            # we probably don't really need this, but for now, it's nice to keep the original e-mail
            notes = notes + line
            #print_v( line.rstrip() )

            # Cron-apt e-mail parsing
            if line.startswith('CRON-APT ACTION: '):
                action = line.rstrip().split(': ')[1]
                updater_is = 'apt'
            elif line.startswith('The following packages will be upgraded'):
                packages_upg_next = 1
                packages_new_next = 0
            elif line.startswith('The following NEW packages will be installed'):
                packages_new_next = 1
                packages_upg_next = 0
            elif line.startswith('E:'):
                errors += 1
            elif line.startswith('W:'):
                warnings += 1
            elif re.search('upgraded, \d+ newly installed',line):
                packages_new_next = 0
                packages_upg_next = 0
            # Apt packages
            elif packages_new_next:
                packages_install += line.strip() + ' '
            elif packages_upg_next:
                packages_upgrade += line.strip() + ' '
            # Yum-cron e-mail parsing
            elif re.search('yum-daily.cron',line):
                updater_is = 'yum'
            elif line.startswith('The following updates will be downloaded on'):
                packages_yum_download = 1
                action = 'downloaded'
                notes += "<pre>\n"
            elif line.startswith('The following updates will be applied on'):
                packages_yum_applied = 1
                action = 'updated'
                notes += "<pre>\n"
            elif line.startswith('Updating:') and packages_yum_download:
                packages_yum_next = 1
            elif line.startswith('Transaction Summary') or line == "\n":
                packages_yum_next = 0
            elif line.startswith('Updates downloaded successfully'):
                errors = 0
                warnings = 0
                notes += "</pre>"
            # Yum package
            elif packages_yum_next:
                # Yum pacakges span multiple lines
                # so we don't reset packages_yum_next here
                yum_package = re.split('\s+',line.strip())
                packages_upgrade += yum_package[0] + ' '
                print_v("Yum packages: " + " - ".join(yum_package))

    packages_upgrade = packages_upgrade.strip()
    return
##################################################################################
# Read the command-line args
command_args(sys.argv[1:])

##################################################################################
# Parse the incoming e-mail first so we can detect YUM or APT
notes = ''
server_name = '-'
action = '-'
packages_install = ''
packages_upgrade = ''
errors = 0
warnings = 0
updater_is = 'unknown'

read_stdin()

print_v('updater ' + updater_is)
print_v('action ' + action)
print_v('packages_install ' + packages_install)
print_v('packages_upgrade ' + packages_upgrade)
print_v('errors %d ' % (errors))
print_v('warnings %d ' % (warnings))

##################################################################################
# Now connect to the Redmine web-server API
if api_authfile:
    read_authfile()

print_v(redmine_url)

try:
    redmine = Redmine(redmine_url, username=api_username, password=api_password, requests={'verify': ssl_checkcert})
except IOError, ioerr:
    print >> sys.stderr, "Error connecting to server: %s: [%d] %s" % (redmine_url, sys.exc_info()[0])
    sys.exit(exit_retry)        # Retry email delivery

# Build standard 'subject' - this will be the key used to create and locate tickets
# Unfortunately, the API does not support globs or regular expressions or substrings, so the subject is not very informative
today = date.today()

cron_updates_subject = 'CRON-%s updates available on %s' % (updater_is.upper(), today.strftime('%Y-%m-%d %a'))
print_v('Subject: ' + cron_updates_subject)

# Build a map of status id's
status_name2id = dict()
status_id2name = dict()
print_v('---- redmine.issue_status object')
issue_status = redmine.issue_status

try:
    for status_obj in issue_status.all():
        status_name2id[status_obj.name.lower()] = status_obj.id
        status_id2name[status_obj.id] = status_obj.name.lower()
        #print_v( list(status_obj) )
except:
    print >> sys.stderr, "Error connecting to redmine %s" % redmine_url
    print >> sys.stderr, sys.exc_info()[0]
    print >> sys.stderr, sys.exc_info()[1]
    sys.exit(exit_retry)        # Retry email delivery

print_v('status_id New = ' + str(status_name2id['new']) )
print_v('status_id Resolved = ' + str(status_name2id['resolved']) )

#------------------ Set the lock ------------------------
lock_and_exitonerror()

# Note: if the user 'apiuser' is not a member of the project 'software-updates', the API just crashes, instead of reporting an error
# Note: must specify status_id='*' or only open issues are reported
# Note: 'apiuser' must be a 'manager' role within the project in order to reset status=new on tickets

try:
    cron_updates_issues = redmine.issue.filter(project_id=redmine_project,subject=cron_updates_subject,status_id='*')
    n_issues = len(cron_updates_issues)
except:
    print "Error retrieving issues from redmine %s" % redmine_url
    print >> sys.stderr, sys.exc_info()[0]
    print >> sys.stderr, sys.exc_info()[1]
    sys.exit(exit_retry)        # Retry email delivery

cron_updates_create_new = 0
if n_issues == 0:
    cron_updates_create_new = 1
    print_v('---- no issues found')
    # No existing ticket - create a new one
    cron_updates_ticket = redmine.issue.new()
    cron_updates_ticket.project_id = redmine_project
    cron_updates_ticket.subject = cron_updates_subject
    # Status = new is the default, but still...
    cron_updates_ticket.status_id = status_name2id['new']
    if updater_is == 'apt':
        cron_updates_ticket.description = \
"""
The following servers have updates ready to install:

|_.Server |_.Action |_.Warn |_.Err |_.Existing Packages |_. NEW Packages |
"""
    else:
        cron_updates_ticket.description = \
"""
The following servers have updates ready to install:

|_.Server |_.Action |_.Err |_.Packages |
"""
else:
    print_v('---- found ' + str(len(cron_updates_issues)) + ' issues')
    print_v('---- using ' + str(cron_updates_issues[0].id))
    print_v(dir(cron_updates_issues[0]))
    print_v('-----')
    print_v(list(cron_updates_issues[0]))
    status_id = int(cron_updates_issues[0].status.id)
    print_v('---- status %d (%s)' % (status_id,status_id2name[status_id]))
    # Found existing ticket(s)
    cron_updates_ticket = cron_updates_issues[0]
    # If this is already closed/resolved, reopen it
    # Don't reopen the ticket if yum has already applied the updates
    if not action.startswith('updated'):
        cron_updates_ticket.status_id = status_name2id['new']

    #cron_updates_ticket.status = {'id':1}

if not ( server_name is '-' or server_name is '' ):
    if updater_is == 'apt':
        cron_updates_ticket.description += "| %s | %s |=. %d |=. %d | %s | %s |\n" % (server_name, action, warnings, errors, packages_upgrade, packages_install)
    elif not packages_upgrade is '':
        cron_updates_ticket.description += "| %s | %s |=. %d | %s |\n" % (server_name, action, errors, packages_upgrade)
    cron_updates_ticket.notes = notes

if noupdate:
    print >> sys.stderr, "Noupdate mode - no updates performed"
else:    
    try:
        cron_updates_ticket.save()
        # notes gets ignored on the creation of a new ticket - update the notes separately
        if cron_updates_create_new:
            cron_updates_ticket.notes = notes
            cron_updates_ticket.save()
    except:
        print "Error updating issue in redmine %s" % redmine_url
        print >> sys.stderr, sys.exc_info()[0]
        print >> sys.stderr, sys.exc_info()[1]
        unlock_and_exit(exit_retry)		# Retry email delivery

unlock_and_exit(exit_ok)
