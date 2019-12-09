"""
Tools for doing dependency mappings for recipes
"""

import sys
import unicodedata
import yaml

def load(fn):
    rslt = []
    try:
      with open(fn, 'r') as stream:
        rslt = yaml.safe_load(stream)
    except:
      print("Unable to load {} as yaml".format(fn))
    # get_for_cran(rslt, 'rcpparmadillo')
    return rslt

def get_sysreqs(deps, sysreqs):
    rslt = []
    strs = []
    for d in sysreqs:
      try:
        v = deps['systemreq']
        for i in v:
           try:
             name = i['dep'].lower()
             if name in d.lower():
               cran_name = 'SR_' + i['as']
               if not cran_name in strs:
                  strs.append(cran_name)
           except:
             pass
      except:
        pass

    try:
      v = deps['dependencies']
      for i in v:
        try:
          fn = i['for_cran']
          for fcn in fn:
            if fcn in strs:
              rslt.append(i)
              break
        except:
          pass
    except:
      pass
    return rslt

def get_for_cran(deps, crandep):
    rslt = []
    try:
      v = deps['dependencies']
      for i in v:
        try:
          fc = i['for_cran']
          if crandep in fc:
              rslt.append(i)
              #ln = get_dep_name(i)
              #print('{}'.format(ln))
        except:
          pass
    except:
      pass
    return rslt

def get_dep_name(dep):
   name = dep['dep']
   ver = ''
   try:
     ver = dep['version']
   except:
     pass
   if ver != '':
     name += ' >=' + ver
   for_os = get_oslimit(dep)
   if for_os != '':
     name += '  # [' + for_os + ']'
   return name

def get_oslimit(dep):
   rslt = ''
   try:
     rslt = dep['oslimit']
   except:
     pass
   return rslt

def get_isskip(dep):
  rslt = ''
  try:
    rslt = dep['skip']
  except:
    pass
  return rslt

def get_addto(dep):
  rslt = []
  try:
    rslt = dep['addto']
  except:
    pass
  return rslt 

#end 
