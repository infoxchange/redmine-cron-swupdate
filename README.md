redmine-cron-swupdate.py - create a Redmine ticket from cron-apt and yum-cron e-mails
=====================================================================================

This is a python script written for the Redmine project management Web application - http://www.redmine.org

It is intended for use by Systems Administrators responsible for keeping Linux systems software up-to-date, and who are using cron-apt (Debian-based Linux) or yum-cron (RedHat-based Linux)

This script will convert e-mails generated by cron-apt and yum-cron into a daily Redmine ticket
This ticket summarises the updates that have been downloaded and are ready to apply.

Installation
------------

mail server Configuration
-------------------------
This script reads a single e-mail message (headers and all) from the standard input, and from this either creates a new ticket or updates an existing ticket.

It can be lauched by the e-mail server (sendmail or postfix or similar) as an alias in `/etc/aliases` or `/etc/postfix/aliases` like this:

```
swupdates:	|"/usr/local/bin/redmine-cron-swupdate.py -s redmine.example.com -A /usr/local/bin/redmine-api.auth"
```

Redmine requires an authenticated user to use the API.

The preferred way of specifying the username and password is via an 'authentication file' such as `/usr/local/bin/redmine-api.auth` in the example above
This file should contain either a username and password, eg:
```
username=autotix
password=XeiGh4ah
```
Or it can contain an API key, which can be obtained from the 'My Account' page when logged in to Redmine as the chosen API user ('autotix' in this example).
If using an API key, the authentication file should contain:
```
apikey=e37c43496a4b66f855cf53c18987d6a71324
```
Substitute the correct value for apikey=... as obtained from the Redmine 'My Account' page

Redmine Configuration
---------------------
This script requires:
* A Redmine project to create tickets in.
The default name for this project is `software-updates`
* A Redmine user to create and update tickets via the API.
This user needs to be a `manager` for the project `software-updates`.
This allows the daily ticket to be re-opened if any new updates arrive.
The username+password or apikey from this user should be used on the mail-server in the 'authentication file'

If the Redmine user is a `developer` or `reporter` instead of a `manager`, the script will still work, but once the ticket is closed, it will remain closed even if thee ticket is updated by a subsequent e-mail.

Note that the script uses the `Subject` field to locate the daily ticket for updating, so the `Subject` should not be editted manually.

yum-cron Configuration
----------------------
On all RedHat client hosts, ensure that `/etc/yum/yum-cron.conf` contains:
```
[commands]
...
apply_updates = no
random_sleep = 60
...
[emitters]
...
emit_via = email
...
[email]
...
email_to = swupdates@mymail.example.com
...
```
The default value for `apply_updates` is yes. If this is changed to `no` then the updates will be downloaded, but not installed automatically.

The default value for random_sleep is 360 (minutes) - ie 6 hours.
Ideally, the updates should run in the early hours of the morning, and be completed before the start of the working day.

cron-apt Configuration
----------------------
On all Debian client hosts, ensure that `/etc/cron-apt/config.d/3-download` contains:
```
MAILTO="swupdates@mymail.example.com"
MAILON="upgrade"
```
Substitute the correct value for swupdates@mymail.example.com

Also ensure that `/etc/cron-apt/action.d/3-download` contains:
```
autoclean -y
dist-upgrade -d -y -o APT::Get::Show-Upgraded=true
```
This is the default setting. The '-d' means 'download only'.

Troubleshooting
---------------
For troubleshooting purposes, this script can be run from the command line like this:
```
/usr/local/bin/redmine-cron-swupdate.py -s redmine.example.com -u autotix -p XeiGh4ah -n -v -k < cron-email-with-headers.txt
-- or --
/usr/local/bin/redmine-cron-swupdate.py -s redmine.example.com -u e37c43496a4b66f855cf53c18987d6a71324 -p anything -n -v -k < cron-email-with-headers.txt
```
where:
    -n ... don't create or update tickets
    -v ... verbose messages
    -k ... don't check the SSL certificate
    -u, -p ... username, password --or-- apikey, unused
    cron-email-with-headers.txt is a plain text file containing 1 entire cron-apt or yum-cron message, including the message headers
