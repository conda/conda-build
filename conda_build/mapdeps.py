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
    strs = []
    v = deps.get("systemreq", [])
    for d in sysreqs:
        for i in v:
             if i.get("dep", '').lower() in d.lower():
               cran_name = i.get("as", '')
               if cran_name and cran_name not in strs:
                  strs.append('SR_' + cran_name)
    return [i for i in deps.get("dependencies", [])
            for fcn in i.get('for_cran', []) if fcn and fcn in strs]

def get_for_cran(deps, crandep):
    return [i for i in deps.get("dependencies", [])
            if crandep and crandep in i.get("for_cran", [])]

def get_dep_name(dep):
   name = dep['dep']
   ver = dep.get("version", '')
   if ver != '':
     name += ' >=' + ver
   for_os = get_oslimit(dep)
   if for_os != '':
     name += '  # [' + for_os + ']'
   return name

def get_oslimit(dep):
   return dep.get("oslimit", '')

def get_isskip(dep):
  return dep.get("skip", '')

def get_addto(dep):
  return dep.get("addto", [])

#end 
