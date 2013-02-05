'''
Created on Jan 22, 2013

@author: abbietrewin
'''
INCONFIG = "/Applications/DL_MONTE/input_for_DL_MONTE/cage4_n2-DL_MONTE/CONFIG_no_c"
CONFIG = "/Applications/DL_MONTE/input_for_DL_MONTE/cage4_n2-DL_MONTE/CONFIG.out"
ATOMS = ['n=','c1','hc_2', 'c2', 'NQ' ]
ATOMS2 = ['cp_1', 'cp_2', 'hc_1', 'c=1','COM' ]

f = open( INCONFIG, "r" )
o = open( CONFIG, "w" )

            
# First 7 lines just info - not needed
for i in range(7):
    line = f.readline()
    o.writeXyz( line )

line = f.readline()
while line:
    #line = line.strip()
    fields = line.split()
    label = fields[0]
    if label in ATOMS:
        newline = label + "      c\n"
        o.writeXyz( newline )
    else:
        if label in ATOMS2:
            newline = label + "    c\n"
            o.writeXyz( newline )
        else:
            o.writeXyz( line )
        
    line = f.readline()

f.close()
o.close() 
        

        
        