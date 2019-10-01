"""
Tools for doing dependency mappings for recipes
"""

import sys
import unicodedata
import yaml

def mapdeps_load(fn):
    rslt = []
    try:
      with open(fn, 'r') as stream:
        rslt = yaml.safe_load(stream)
    except:
      print("Unable to load {} as yaml".format(fn))
    mapdeps_get_for_cran(rslt, 'rcpparmadillo')
    return rslt

def mapdeps_get_for_cran(deps, crandep):
    rslt = []
    try:
      v = deps['dependencies']
      for i in v:
        try:
          fc = i['for_cran']
          if crandep in fc:
              rslt.append(i)
              ln = mapdeps_get_dep_name(i)
              print('{}'.format(ln))
        except:
          pass
    except:
      pass
    return rslt

def mapdeps_get_dep_name(dep):
   name = dep['dep']
   ver = ''
   try:
     ver = dep['version']
   except:
     pass
   if ver != '':
     name += ' >=' + ver
   for_os = mapdeps_get_oslimit(dep)
   if for_os != '':
     name += '  # [' + for_os + ']'
   return name

def mapdeps_get_oslimit(dep):
   rslt = ''
   try:
     rslt = dep['oslimit']
   except:
     pass
   return rslt

#end 
