#!/usr/bin/env perl

use strict;
use warnings;
use Module::CoreList;
use Data::Dumper qw(Dumper);

my @modules;
@modules = Module::CoreList->find_modules(qr/.*/);
foreach (@modules) {
  my $mod = $_;
  my $ver;
  $ver = $^V;
  $ver = "v5.8.8";
  use version; $ver = version->parse($ver);
  print("ver (dotted) $ver\n");
  $ver = "5.021009";
  print("$ver ver $ver ver\n");
  my $version_hash;
  $version_hash = Module::CoreList->find_version($ver);
  if ($version_hash) {
    # print(Dumper([$version_hash]), "\n");
    print($mod, " ", $version_hash->{$mod}, "\n");
    print("version hash $version_hash->{$mod}\n");
  }

  # printf("%s %s %s %s\n", $mod, $ver, $Module::CoreList::version{$ver}{$mod}, "wtf\n");
  # printf("%s %s %s\n", $mod, $ver, $Module::CoreList::version{$ver}{$mod} || 'undef' if exists $Module::CoreList::version{$ver}{$mod});

#  for my $v(
#      sort keys %Module::CoreList::version ){
#      printf "  %-10s %-10s\n",
#          $v,
#          $Module::CoreList::version{$v}{$mod}
#              || 'undef'
#              if exists $Module::CoreList::version{$v}{$mod};
#  }
}
