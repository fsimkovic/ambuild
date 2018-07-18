'''
Created on 14 Jun 2016

@author: jmht
'''

import random as _random

class subUnit(object):
    # These are referenced by all endPoints
    monomoers = None
    ratio = None
    totalTally = None # Keeps track of overall tally in polymer
    def __init__(self, monomers, ratio, polymer, totalTally, direction=1, fragment=None, random=False):
        self.monomers = monomers
        self.ratio = ratio
        self.direction = direction
        if direction > 0:
            self.index = 0
        else:
            self.index = len(monomers) - 1
        self.tally = [0] * len(monomers) # Tracks how many monomers are present in this subunit
        self.totalTally = totalTally # Tracks how many monomers are present in the overall polymer
        self.random = random
        self.polymer = polymer
        if fragment is not None:
            self.incrementMonomer(fragment) # We have added a fragment so increment things
        else:
            # The first subunit is intialised with the poymer and a monomer. Subsequent subunits don't have an initial monomer 
            # but build outwards from the first polymer monomer so we just need to set the fragment, not increment
            self.fragment = self.polymer.fragments[0]
        return
    
    def addMonomer(self, mycell):
        # Start working from endPoint1 going forward
        polymerEndGroups = self.polymerEndGroups()
        monomer = self.nextMonomerType()
        newBlock = mycell.getLibraryBlock(fragmentType=monomer)
        monomerEndGroups = newBlock.freeEndGroups()
        got = False
        for polymerEndGroup in polymerEndGroups:
            if got:
                break
            for monomerEndGroup in monomerEndGroups:
                ok = mycell.attachBlock(monomerEndGroup, polymerEndGroup, dihedral=None)
                if ok:
                    self.incrementMonomer(monomerEndGroup.fragment)
                    got = True
                    break
        return got
    
    def incrementMonomer(self, fragment):
        """Add the next monomer and update the data structures"""
        self.totalTally[self.index] += 1
        if not self.random:
            # Add one to the tally at this position
            self.tally[self.index] += 1
            assert self.tally[self.index] <= self.ratio[self.index],\
                    "Exceeded permissible monomers at position: {0}".format(self.index)
            # See if we have added enough monomers of this type
            if self.tally[self.index] == self.ratio[self.index]:
                # Need to move along to the next one
                if self.direction > 0:
                    if self.index == len(self.tally) - 1:
                        self.index = 0
                        # Reset tally
                        self.tally = [0] * len(self.monomers)
                    else:
                        self.index += 1
                elif self.direction < 0:
                    if self.index == 0:
                        self.index = len(self.tally) - 1
                        # Reset tally
                        self.tally = [0] * len(self.monomers)
                    else:
                        self.index -= 1
        # Now need to update the fragment we are pointing at
        self.fragment = fragment
        return
    
    def polymerEndGroups(self):
        assert self.fragment
        return self.polymer.freeEndGroups(fragment=self.fragment)

    def nextMonomerType(self):
        """Return the next endGroupType required to continue this subUnit"""
        if self.random:
            return self.randomMonomerType()
        else:
            return self.monomers[self.index]
    
    def randomMonomerType(self):
        """Determine a random MonomerType to return
        
        We use an interval of length one, binned by the relative sizes of ratios
        At the start the bins are the same size as the ratios. As the totalTally 
        is updated, we multiply the ideal ratios by the difference between them and 
        the current ratio from the totalTally. If a particular monomer is over-represented
        then the bin of that monomer will be decreased and there will be less chance of selection
        that monomer.
        """
        # Calculate the ideal weights based on the ratios
        rTotal = sum(self.ratio)
        idealWeights = [ float(r)/float(rTotal) for r in self.ratio ]
        # If we don't have any of monomers in the polymer yet, we use the ideal
        # weights for everything
        if 0 in self.totalTally:
            weights = idealWeights
        else:
            # Calculate the current ratios
            tTotal = sum(self.totalTally)
            currentWeights = []
            for r in self.totalTally:
                if r > 0:
                    w = float(r)/float(tTotal)
                else:
                    w = 0.0
                currentWeights.append(w) 
            # By dividing the ideal weight by the current weight, if the current weight is smaller than the ideal
            # the result of the division is > 1, so by multiplying by the result, we increase the weight for that monomer
            weights = []
            for wi, wc in zip(idealWeights,currentWeights):
                if wc == 0.0:
                    w = wi
                else:
                    w = wi* wi/wc 
                weights.append(w)
            # We need to divide each by the sum to bring back onto a common scale
            wsum = sum(weights)
            weights = [ w/wsum for w in weights]
        pin = _random.uniform(0,1)
        # See which bin the pin landed in
        high = 0.0
        index = None
        for i, w in enumerate(weights):
            high += w
            if pin <= high:
                index = i
                break
        assert index is not None, "Didn't catch value!"
        # Set index so that we know which monomer we added
        self.index = index
        return self.monomers[self.index]
