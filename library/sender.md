## Linux

## Windows

## MacOS

### Installation Guide

When the container starts up for the first time it will automatically download
the desired macOS version. After the download open the QEMU interface
in the browser, the default ports are 8007 and 8008.

Click Utility and in that windows choose the largest disk out of the 3
and click 'Erase' and give the disk a name.
Then go back to the main screen and choose to reinstall the OS.
Go through the installation, it takes a while, and after the main installation
you'll be prompted with options such as country, language, etc...
opt out of any feature and choose the most basic options.

After the OS finished installing, open the terminal and run the following commands:

`sudo -S mount_9p shared`

`cd /Volumes/shared`

Then run:

`./run_kyber.sh` or `./run_mlkem.sh`

Press Enter to allow downloading Xcode. Download Xcode takes a while.
After that you will be prompted a few times to enter your password for
sudo privileges. If you missed it just run the file again, and you'll be
prompted for it.

When the script ends the sender should be listening on port 5000.
To make sure it works go to localhost:5000 on Safari and see if it runs.