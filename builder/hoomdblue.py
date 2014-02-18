import platform
import sys

from socket import gethostname

# can't do below as I think this needs to be set before the python interpreter is started.
#os.environ['DYLD_LIBRARY_PATH'] = "/Applications/HOOMD-blue.app/Contents/MacOS"

if platform.system() == "Darwin":
    sys.path.append("/Applications/HOOMD-blue.app/Contents/lib/hoomd/python-module")
    sys.path.append("/Applications/HOOMD-blue.app/Contents/MacOS")
    
elif gethostname() == "cytosine":
    sys.path.append("/home/jmht/Downloads/hoomd-0.11.3/install/lib/hoomd/python-module")
    sys.path.append("/home/jmht/Downloads/hoomd-0.11.3/install/bin") 
    
else:
    sys.path.append("/opt/hoomd-0.11.3/hoomdblue-install/lib/hoomd/python-module")
    sys.path.append("/opt/hoomd-0.11.3/hoomdblue-install/bin") 

from hoomd_script import *


