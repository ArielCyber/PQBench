## Overview
This repository is part of a whole framework. The purpose of this process is to lay the foundations of
creating Post Quantum Cryptography (PQC) encryption data creation.

## Project Structure
The project is divided to the following:

**agent** - a container that is responsible to receive the input from the framework and move it forward

**switcher** - a container that is responsible for managing the work of the different containers

**sender_linux** - defines containers that are responsible for creating traffic to a server with different
browsers and algorithms

**sender_windows** - defines containers that are responsible for creating traffic to a server with different
browsers and algorithms

**sniffer** - defines a container that is responsible for recording and saving the traffic from all 
the different senders

**domain_maintainer** - defines a container that is responsible for handling the different domains databases
that are contained in .xlsx files

**docker-compose** - builds all the different containers

**.env** - file that contains the different environment variables in the docker-compose


![img.png](images/active_recording_diagram.png)