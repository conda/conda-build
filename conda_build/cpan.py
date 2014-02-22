"""
Tools for converting CPAN packages to conda recipes.
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import json
import sys
from io import open
from os import makedirs
from os.path import basename, dirname, join, exists

from conda.fetch import download, TmpDownload
from conda.utils import human_bytes, hashsum_file
from conda.install import rm_rf
from conda_build.utils import tar_xf, unzip
from conda_build.source import SRC_CACHE
from conda.compat import input, configparser, StringIO

# This monstrosity is the set of everything in the Perl core as of 5.18.2
# I also added "perl" to the list for simplicity of filtering later
PERL_CORE = {'AnyDBM_File', 'App::Cpan', 'App::Prove', 'App::Prove::State',
             'App::Prove::State::Result', 'App::Prove::State::Result::Test',
             'Archive::Extract', 'Archive::Tar', 'Archive::Tar::Constant',
             'Archive::Tar::File', 'Attribute::Handlers', 'AutoLoader',
             'AutoSplit', 'B', 'B::Concise', 'B::Debug', 'B::Deparse',
             'B::Lint', 'B::Lint::Debug', 'B::Showlex', 'B::Terse', 'B::Xref',
             'Benchmark', 'CGI', 'CGI::Apache', 'CGI::Carp', 'CGI::Cookie',
             'CGI::Fast', 'CGI::Pretty', 'CGI::Push', 'CGI::Switch',
             'CGI::Util', 'CPAN', 'CPAN::Author', 'CPAN::Bundle',
             'CPAN::CacheMgr', 'CPAN::Complete', 'CPAN::Debug',
             'CPAN::DeferredCode', 'CPAN::Distribution', 'CPAN::Distroprefs',
             'CPAN::Distrostatus', 'CPAN::Exception::RecursiveDependency',
             'CPAN::Exception::blocked_urllist',
             'CPAN::Exception::yaml_not_installed',
             'CPAN::Exception::yaml_process_error', 'CPAN::FTP',
             'CPAN::FTP::netrc', 'CPAN::FirstTime', 'CPAN::HTTP::Client',
             'CPAN::HTTP::Credentials', 'CPAN::HandleConfig', 'CPAN::Index',
             'CPAN::InfoObj', 'CPAN::Kwalify', 'CPAN::LWP::UserAgent',
             'CPAN::Meta', 'CPAN::Meta::Converter', 'CPAN::Meta::Feature',
             'CPAN::Meta::History', 'CPAN::Meta::Prereqs',
             'CPAN::Meta::Requirements', 'CPAN::Meta::Spec',
             'CPAN::Meta::Validator', 'CPAN::Meta::YAML', 'CPAN::Mirrors',
             'CPAN::Module', 'CPAN::Nox', 'CPAN::Prompt', 'CPAN::Queue',
             'CPAN::Shell', 'CPAN::Tarzip', 'CPAN::URL', 'CPAN::Version',
             'CPANPLUS', 'CPANPLUS::Backend', 'CPANPLUS::Backend::RV',
             'CPANPLUS::Config', 'CPANPLUS::Config::HomeEnv',
             'CPANPLUS::Configure', 'CPANPLUS::Configure::Setup',
             'CPANPLUS::Dist', 'CPANPLUS::Dist::Autobundle',
             'CPANPLUS::Dist::Base', 'CPANPLUS::Dist::Build',
             'CPANPLUS::Dist::Build::Constants', 'CPANPLUS::Dist::MM',
             'CPANPLUS::Dist::Sample', 'CPANPLUS::Error', 'CPANPLUS::Internals',
             'CPANPLUS::Internals::Constants',
             'CPANPLUS::Internals::Constants::Report',
             'CPANPLUS::Internals::Extract', 'CPANPLUS::Internals::Fetch',
             'CPANPLUS::Internals::Report', 'CPANPLUS::Internals::Search',
             'CPANPLUS::Internals::Source',
             'CPANPLUS::Internals::Source::Memory',
             'CPANPLUS::Internals::Source::SQLite',
             'CPANPLUS::Internals::Source::SQLite::Tie',
             'CPANPLUS::Internals::Utils',
             'CPANPLUS::Internals::Utils::Autoflush', 'CPANPLUS::Module',
             'CPANPLUS::Module::Author', 'CPANPLUS::Module::Author::Fake',
             'CPANPLUS::Module::Checksums', 'CPANPLUS::Module::Fake',
             'CPANPLUS::Module::Signature', 'CPANPLUS::Selfupdate',
             'CPANPLUS::Shell', 'CPANPLUS::Shell::Classic',
             'CPANPLUS::Shell::Default',
             'CPANPLUS::Shell::Default::Plugins::CustomSource',
             'CPANPLUS::Shell::Default::Plugins::Remote',
             'CPANPLUS::Shell::Default::Plugins::Source', 'Carp', 'Carp::Heavy',
             'Class::Struct', 'Compress::Raw::Bzip2', 'Compress::Raw::Zlib',
             'Compress::Zlib', 'Config', 'Config::Extensions',
             'Config::Perl::V', 'Cwd', 'DB', 'DBM_Filter',
             'DBM_Filter::compress', 'DBM_Filter::encode', 'DBM_Filter::int32',
             'DBM_Filter::null', 'DBM_Filter::utf8', 'DB_File', 'Data::Dumper',
             'Devel::InnerPackage', 'Devel::PPPort', 'Devel::Peek',
             'Devel::SelfStubber', 'Digest', 'Digest::MD5', 'Digest::SHA',
             'Digest::base', 'Digest::file', 'DirHandle', 'Dumpvalue',
             'DynaLoader', 'Encode', 'Encode::Alias', 'Encode::Byte',
             'Encode::CJKConstants', 'Encode::CN', 'Encode::CN::HZ',
             'Encode::Config', 'Encode::EBCDIC', 'Encode::Encoder',
             'Encode::Encoding', 'Encode::GSM0338', 'Encode::Guess',
             'Encode::JP', 'Encode::JP::H2Z', 'Encode::JP::JIS7', 'Encode::KR',
             'Encode::KR::2022_KR', 'Encode::MIME::Header',
             'Encode::MIME::Header::ISO_2022_JP', 'Encode::MIME::Name',
             'Encode::Symbol', 'Encode::TW', 'Encode::Unicode',
             'Encode::Unicode::UTF7', 'English', 'Env', 'Errno', 'Exporter',
             'Exporter::Heavy', 'ExtUtils::CBuilder',
             'ExtUtils::CBuilder::Base', 'ExtUtils::CBuilder::Platform::Unix',
             'ExtUtils::CBuilder::Platform::VMS',
             'ExtUtils::CBuilder::Platform::Windows',
             'ExtUtils::CBuilder::Platform::Windows::BCC',
             'ExtUtils::CBuilder::Platform::Windows::GCC',
             'ExtUtils::CBuilder::Platform::Windows::MSVC',
             'ExtUtils::CBuilder::Platform::aix',
             'ExtUtils::CBuilder::Platform::cygwin',
             'ExtUtils::CBuilder::Platform::darwin',
             'ExtUtils::CBuilder::Platform::dec_osf',
             'ExtUtils::CBuilder::Platform::os2', 'ExtUtils::Command',
             'ExtUtils::Command::MM', 'ExtUtils::Constant',
             'ExtUtils::Constant::Base', 'ExtUtils::Constant::ProxySubs',
             'ExtUtils::Constant::Utils', 'ExtUtils::Constant::XS',
             'ExtUtils::Embed', 'ExtUtils::Install', 'ExtUtils::Installed',
             'ExtUtils::Liblist', 'ExtUtils::Liblist::Kid', 'ExtUtils::MM',
             'ExtUtils::MM_AIX', 'ExtUtils::MM_Any', 'ExtUtils::MM_BeOS',
             'ExtUtils::MM_Cygwin', 'ExtUtils::MM_DOS', 'ExtUtils::MM_Darwin',
             'ExtUtils::MM_MacOS', 'ExtUtils::MM_NW5', 'ExtUtils::MM_OS2',
             'ExtUtils::MM_QNX', 'ExtUtils::MM_UWIN', 'ExtUtils::MM_Unix',
             'ExtUtils::MM_VMS', 'ExtUtils::MM_VOS', 'ExtUtils::MM_Win32',
             'ExtUtils::MM_Win95', 'ExtUtils::MY', 'ExtUtils::MakeMaker',
             'ExtUtils::MakeMaker::Config', 'ExtUtils::Manifest',
             'ExtUtils::Miniperl', 'ExtUtils::Mkbootstrap',
             'ExtUtils::Mksymlists', 'ExtUtils::Packlist', 'ExtUtils::ParseXS',
             'ExtUtils::ParseXS::Constants', 'ExtUtils::ParseXS::CountLines',
             'ExtUtils::ParseXS::Utilities', 'ExtUtils::Typemaps',
             'ExtUtils::Typemaps::Cmd', 'ExtUtils::Typemaps::InputMap',
             'ExtUtils::Typemaps::OutputMap', 'ExtUtils::Typemaps::Type',
             'ExtUtils::XSSymSet', 'ExtUtils::testlib', 'Fatal', 'Fcntl',
             'File::Basename', 'File::CheckTree', 'File::Compare', 'File::Copy',
             'File::DosGlob', 'File::Fetch', 'File::Find', 'File::Glob',
             'File::GlobMapper', 'File::Path', 'File::Spec',
             'File::Spec::Cygwin', 'File::Spec::Epoc', 'File::Spec::Functions',
             'File::Spec::Mac', 'File::Spec::OS2', 'File::Spec::Unix',
             'File::Spec::VMS', 'File::Spec::Win32', 'File::Temp', 'File::stat',
             'FileCache', 'FileHandle', 'Filter::Simple', 'Filter::Util::Call',
             'FindBin', 'GDBM_File', 'Getopt::Long', 'Getopt::Std',
             'HTTP::Tiny', 'Hash::Util', 'Hash::Util::FieldHash',
             'I18N::Collate', 'I18N::LangTags', 'I18N::LangTags::Detect',
             'I18N::LangTags::List', 'I18N::Langinfo', 'IO',
             'IO::Compress::Adapter::Bzip2', 'IO::Compress::Adapter::Deflate',
             'IO::Compress::Adapter::Identity', 'IO::Compress::Base',
             'IO::Compress::Base::Common', 'IO::Compress::Bzip2',
             'IO::Compress::Deflate', 'IO::Compress::Gzip',
             'IO::Compress::Gzip::Constants', 'IO::Compress::RawDeflate',
             'IO::Compress::Zip', 'IO::Compress::Zip::Constants',
             'IO::Compress::Zlib::Constants', 'IO::Compress::Zlib::Extra',
             'IO::Dir', 'IO::File', 'IO::Handle', 'IO::Pipe', 'IO::Poll',
             'IO::Seekable', 'IO::Select', 'IO::Socket', 'IO::Socket::INET',
             'IO::Socket::UNIX', 'IO::Uncompress::Adapter::Bunzip2',
             'IO::Uncompress::Adapter::Identity',
             'IO::Uncompress::Adapter::Inflate', 'IO::Uncompress::AnyInflate',
             'IO::Uncompress::AnyUncompress', 'IO::Uncompress::Base',
             'IO::Uncompress::Bunzip2', 'IO::Uncompress::Gunzip',
             'IO::Uncompress::Inflate', 'IO::Uncompress::RawInflate',
             'IO::Uncompress::Unzip', 'IO::Zlib', 'IPC::Cmd', 'IPC::Msg',
             'IPC::Open2', 'IPC::Open3', 'IPC::Semaphore', 'IPC::SharedMem',
             'IPC::SysV', 'JSON::PP', 'JSON::PP::Boolean', 'List::Util',
             'List::Util::XS', 'Locale::Codes', 'Locale::Codes::Constants',
             'Locale::Codes::Country', 'Locale::Codes::Country_Codes',
             'Locale::Codes::Country_Retired', 'Locale::Codes::Currency',
             'Locale::Codes::Currency_Codes', 'Locale::Codes::Currency_Retired',
             'Locale::Codes::LangExt', 'Locale::Codes::LangExt_Codes',
             'Locale::Codes::LangExt_Retired', 'Locale::Codes::LangFam',
             'Locale::Codes::LangFam_Codes', 'Locale::Codes::LangFam_Retired',
             'Locale::Codes::LangVar', 'Locale::Codes::LangVar_Codes',
             'Locale::Codes::LangVar_Retired', 'Locale::Codes::Language',
             'Locale::Codes::Language_Codes', 'Locale::Codes::Language_Retired',
             'Locale::Codes::Script', 'Locale::Codes::Script_Codes',
             'Locale::Codes::Script_Retired', 'Locale::Country',
             'Locale::Currency', 'Locale::Language', 'Locale::Maketext',
             'Locale::Maketext::Guts', 'Locale::Maketext::GutsLoader',
             'Locale::Maketext::Simple', 'Locale::Script', 'Log::Message',
             'Log::Message::Config', 'Log::Message::Handlers',
             'Log::Message::Item', 'Log::Message::Simple', 'MIME::Base64',
             'MIME::QuotedPrint', 'Math::BigFloat', 'Math::BigFloat::Trace',
             'Math::BigInt', 'Math::BigInt::Calc', 'Math::BigInt::CalcEmu',
             'Math::BigInt::FastCalc', 'Math::BigInt::Trace', 'Math::BigRat',
             'Math::Complex', 'Math::Trig', 'Memoize', 'Memoize::AnyDBM_File',
             'Memoize::Expire', 'Memoize::ExpireFile', 'Memoize::ExpireTest',
             'Memoize::NDBM_File', 'Memoize::SDBM_File', 'Memoize::Storable',
             'Module::Build', 'Module::Build::Base', 'Module::Build::Compat',
             'Module::Build::Config', 'Module::Build::ConfigData',
             'Module::Build::Cookbook', 'Module::Build::Dumper',
             'Module::Build::ModuleInfo', 'Module::Build::Notes',
             'Module::Build::PPMMaker', 'Module::Build::Platform::Amiga',
             'Module::Build::Platform::Default',
             'Module::Build::Platform::EBCDIC',
             'Module::Build::Platform::MPEiX', 'Module::Build::Platform::MacOS',
             'Module::Build::Platform::RiscOS', 'Module::Build::Platform::Unix',
             'Module::Build::Platform::VMS', 'Module::Build::Platform::VOS',
             'Module::Build::Platform::Windows', 'Module::Build::Platform::aix',
             'Module::Build::Platform::cygwin',
             'Module::Build::Platform::darwin', 'Module::Build::Platform::os2',
             'Module::Build::PodParser', 'Module::Build::Version',
             'Module::Build::YAML', 'Module::CoreList',
             'Module::CoreList::TieHashDelta', 'Module::CoreList::Utils',
             'Module::Load', 'Module::Load::Conditional', 'Module::Loaded',
             'Module::Metadata', 'Module::Pluggable',
             'Module::Pluggable::Object', 'Moped::Msg', 'NDBM_File', 'NEXT',
             'Net::Cmd', 'Net::Config', 'Net::Domain', 'Net::FTP',
             'Net::FTP::A', 'Net::FTP::E', 'Net::FTP::I', 'Net::FTP::L',
             'Net::FTP::dataconn', 'Net::NNTP', 'Net::Netrc', 'Net::POP3',
             'Net::Ping', 'Net::SMTP', 'Net::Time', 'Net::hostent',
             'Net::netent', 'Net::protoent', 'Net::servent', 'O', 'ODBM_File',
             'Object::Accessor', 'Opcode', 'POSIX', 'Package::Constants',
             'Params::Check', 'Parse::CPAN::Meta', 'Perl::OSType', 'PerlIO',
             'PerlIO::encoding', 'PerlIO::mmap', 'PerlIO::scalar',
             'PerlIO::via', 'PerlIO::via::QuotedPrint', 'Pod::Checker',
             'Pod::Escapes', 'Pod::Find', 'Pod::Functions',
             'Pod::Functions::Functions', 'Pod::Html', 'Pod::InputObjects',
             'Pod::LaTeX', 'Pod::Man', 'Pod::ParseLink', 'Pod::ParseUtils',
             'Pod::Parser', 'Pod::Perldoc', 'Pod::Perldoc::BaseTo',
             'Pod::Perldoc::GetOptsOO', 'Pod::Perldoc::ToANSI',
             'Pod::Perldoc::ToChecker', 'Pod::Perldoc::ToMan',
             'Pod::Perldoc::ToNroff', 'Pod::Perldoc::ToPod',
             'Pod::Perldoc::ToRtf', 'Pod::Perldoc::ToTerm',
             'Pod::Perldoc::ToText', 'Pod::Perldoc::ToTk',
             'Pod::Perldoc::ToXml', 'Pod::PlainText', 'Pod::Select',
             'Pod::Simple', 'Pod::Simple::BlackBox', 'Pod::Simple::Checker',
             'Pod::Simple::Debug', 'Pod::Simple::DumpAsText',
             'Pod::Simple::DumpAsXML', 'Pod::Simple::HTML',
             'Pod::Simple::HTMLBatch', 'Pod::Simple::HTMLLegacy',
             'Pod::Simple::LinkSection', 'Pod::Simple::Methody',
             'Pod::Simple::Progress', 'Pod::Simple::PullParser',
             'Pod::Simple::PullParserEndToken',
             'Pod::Simple::PullParserStartToken',
             'Pod::Simple::PullParserTextToken', 'Pod::Simple::PullParserToken',
             'Pod::Simple::RTF', 'Pod::Simple::Search',
             'Pod::Simple::SimpleTree', 'Pod::Simple::Text',
             'Pod::Simple::TextContent', 'Pod::Simple::TiedOutFH',
             'Pod::Simple::Transcode', 'Pod::Simple::TranscodeDumb',
             'Pod::Simple::TranscodeSmart', 'Pod::Simple::XHTML',
             'Pod::Simple::XMLOutStream', 'Pod::Text', 'Pod::Text::Color',
             'Pod::Text::Overstrike', 'Pod::Text::Termcap', 'Pod::Usage',
             'SDBM_File', 'Safe', 'Scalar::Util', 'Search::Dict', 'SelectSaver',
             'SelfLoader', 'Socket', 'Storable', 'Symbol', 'Sys::Hostname',
             'Sys::Syslog', 'Sys::Syslog::Win32', 'TAP::Base',
             'TAP::Formatter::Base', 'TAP::Formatter::Color',
             'TAP::Formatter::Console',
             'TAP::Formatter::Console::ParallelSession',
             'TAP::Formatter::Console::Session', 'TAP::Formatter::File',
             'TAP::Formatter::File::Session', 'TAP::Formatter::Session',
             'TAP::Harness', 'TAP::Object', 'TAP::Parser',
             'TAP::Parser::Aggregator', 'TAP::Parser::Grammar',
             'TAP::Parser::Iterator', 'TAP::Parser::Iterator::Array',
             'TAP::Parser::Iterator::Process', 'TAP::Parser::Iterator::Stream',
             'TAP::Parser::IteratorFactory', 'TAP::Parser::Multiplexer',
             'TAP::Parser::Result', 'TAP::Parser::Result::Bailout',
             'TAP::Parser::Result::Comment', 'TAP::Parser::Result::Plan',
             'TAP::Parser::Result::Pragma', 'TAP::Parser::Result::Test',
             'TAP::Parser::Result::Unknown', 'TAP::Parser::Result::Version',
             'TAP::Parser::Result::YAML', 'TAP::Parser::ResultFactory',
             'TAP::Parser::Scheduler', 'TAP::Parser::Scheduler::Job',
             'TAP::Parser::Scheduler::Spinner', 'TAP::Parser::Source',
             'TAP::Parser::SourceHandler',
             'TAP::Parser::SourceHandler::Executable',
             'TAP::Parser::SourceHandler::File',
             'TAP::Parser::SourceHandler::Handle',
             'TAP::Parser::SourceHandler::Perl',
             'TAP::Parser::SourceHandler::RawTAP', 'TAP::Parser::Utils',
             'TAP::Parser::YAMLish::Reader', 'TAP::Parser::YAMLish::Writer',
             'Term::ANSIColor', 'Term::Cap', 'Term::Complete', 'Term::ReadLine',
             'Term::UI', 'Term::UI::History', 'Test', 'Test::Builder',
             'Test::Builder::Module', 'Test::Builder::Tester',
             'Test::Builder::Tester::Color', 'Test::Harness', 'Test::More',
             'Test::Simple', 'Text::Abbrev', 'Text::Balanced',
             'Text::ParseWords', 'Text::Soundex', 'Text::Tabs', 'Text::Wrap',
             'Thread', 'Thread::Queue', 'Thread::Semaphore', 'Tie::Array',
             'Tie::File', 'Tie::Handle', 'Tie::Hash', 'Tie::Hash::NamedCapture',
             'Tie::Memoize', 'Tie::RefHash', 'Tie::Scalar', 'Tie::StdHandle',
             'Tie::SubstrHash', 'Time::HiRes', 'Time::Local', 'Time::Piece',
             'Time::Seconds', 'Time::gmtime', 'Time::localtime', 'Time::tm',
             'UNIVERSAL', 'Unicode', 'Unicode::Collate',
             'Unicode::Collate::CJK::Big5', 'Unicode::Collate::CJK::GB2312',
             'Unicode::Collate::CJK::JISX0208', 'Unicode::Collate::CJK::Korean',
             'Unicode::Collate::CJK::Pinyin', 'Unicode::Collate::CJK::Stroke',
             'Unicode::Collate::CJK::Zhuyin', 'Unicode::Collate::Locale',
             'Unicode::Normalize', 'Unicode::UCD', 'User::grent', 'User::pwent',
             'VMS::DCLsym', 'VMS::Stdio', 'Win32', 'Win32API::File',
             'Win32API::File::ExtUtils::Myconst2perl', 'Win32CORE',
             'XS::APItest', 'XS::Typemap', 'XSLoader', '_charnames', 'arybase',
             'attributes', 'autodie', 'autodie::exception',
             'autodie::exception::system', 'autodie::hints', 'autouse', 'base',
             'bigint', 'bignum', 'bigrat', 'blib', 'bytes', 'charnames',
             'constant', 'deprecate', 'diagnostics', 'encoding',
             'encoding::warnings', 'feature', 'fields', 'filetest', 'if',
             'inc::latest', 'integer', 'less', 'lib', 'locale', 'mro', 'open',
             'ops', 'overload', 'overload::numbers', 'overloading', 'parent',
             'perl', 'perlfaq', 're', 'sigtrap', 'sort', 'strict', 'subs',
             'threads', 'threads::shared', 'unicore::Name', 'utf8', 'vars',
             'version', 'vmsish', 'warnings', 'warnings::register'}

CPAN_META = """\
package:
  name: {packagename}
  version: !!str {version}

source:
  fn: {filename}
  url: {cpanurl}
  {usemd5}md5: {md5}
#  patches:
   # List any patch files here
   # - fix.patch

{build_comment}build:
  # If this is a new build for the same version, increment the build
  # number. If you do not include this key, it defaults to 0.
  # number: 1

requirements:
  build:
    - perl{build_depends}

  run:
    - perl{run_depends}

# test:
  # By default CPAN tests will be run while "building" (which just uses cpanm
  # to install)

  # You can also put a file called run_test.py in the recipe that will be run
  # at test time.

  # requires:
    # Put any additional test requirements here.  For example
    # - nose

about:
  home: {homeurl}
  license: {license}
  summary: {summary}

# See
# http://docs.continuum.io/conda/build.html for
# more information about meta.yaml
"""

CPAN_BUILD_SH = """\
#!/bin/bash

cpanm .

# Add more build steps here, if they are necessary.

# See
# http://docs.continuum.io/conda/build.html
# for a list of environment variables that are set during the build process.
"""

CPAN_BLD_BAT = """\
cpanm .
if errorlevel 1 exit 1

:: Add more build steps here, if they are necessary.

:: See
:: http://docs.continuum.io/conda/build.html
:: for a list of environment variables that are set during the build process.
"""

def main(args, parser):
    '''
    Creates a bunch of CPAN conda recipes.
    '''

    package_dicts = {}
    [output_dir] = args.output_dir
    indent = '\n    - '
    args.packages = list(reversed(args.packages))
    while args.packages:
        package = args.packages.pop()

        # Convert modules into distributions
        orig_package = package
        package = dist_for_module(args.meta_cpan_url, package)
        if package not in {orig_package, orig_package.replace('::', '-')}:
            print(("WARNING: {0} was part of the {1} distribution, so we are " +
                   "making a recipe for {1} instead.").format(orig_package,
                                                              package))

        dir_path = join(output_dir, package.lower())
        packagename = perl_to_conda(package)
        if exists(dir_path):
            raise RuntimeError("directory already exists: %s" % dir_path)
        d = package_dicts.setdefault(package, {'packagename': packagename,
                                               'run_depends':'',
                                               'build_depends':'',
                                               'build_comment':'# ',
                                               'test_commands':'',
                                               'usemd5':''})

        # Fetch all metadata from CPAN
        release_data = get_release_info(args.meta_cpan_url, package,
                                        args.version)

        d['cpanurl'] = release_data['download_url']
        d['md5'], size = get_checksum_and_size(release_data['download_url'])
        d['filename'] = release_data['archive']

        print("Using url %s (%s) for %s." % (d['cpanurl'], size, package))

        try:
            d['homeurl'] = release_data['resources']['homepage']
        except KeyError:
            d['homeurl'] = 'http://metacpan.org/pod/' + package
        d['summary'] = repr(release_data['abstract']).lstrip('u')
        d['license'] = release_data['license'][0]
        d['version'] = release_data['version']

        # Create lists of dependencies
        build_deps = set()
        run_deps = set()
        for dep_dict in release_data['dependency']:
            # Only care about requirements
            if dep_dict['relationship'] == 'requires':
                # Format dependency string (with Perl trailing dist comment)
                orig_dist = dist_for_module(args.meta_cpan_url,
                                            dep_dict['module'])
                # Don't add Perl built-ins, unless newer version
                if orig_dist.lower() == 'perl' or (dep_dict['module'] in
                                                   PERL_CORE and
                                                   dep_dict['version'] == '0'):
                    continue
                dep_entry = perl_to_conda(orig_dist)

                # If recursive, check if we have a recipe for this dependency
                if args.recursive and not exists(join(output_dir, dep_entry)):
                    args.packages.append(orig_dist)

                if dep_dict['version_numified']:
                    dep_entry += ' ' + dep_dict['version']
                dep_entry += ' # ' + orig_dist

                # Add to appropriate dependency list
                if dep_dict['phase'] == 'runtime':
                    run_deps.add(dep_entry)
                # Handle build deps
                else:
                    build_deps.add(dep_entry)

        # Add dependencies to d
        d['build_depends'] = indent.join([''] + list(build_deps))
        d['run_depends'] = indent.join([''] + list(run_deps))

        # Write recipe files
        package_dir = join(output_dir, packagename)
        if not exists(package_dir):
            makedirs(package_dir)
        print("Writing recipe for %s" % packagename)
        with open(join(package_dir, 'meta.yaml'), 'w') as f:
            f.write(CPAN_META.format(**d))
        with open(join(package_dir, 'build.sh'), 'w') as f:
            f.write(CPAN_BUILD_SH.format(**d))
        with open(join(package_dir, 'bld.bat'), 'w') as f:
            f.write(CPAN_BLD_BAT.format(**d))

    print("Done")


def dist_for_module(cpan_url, module):
    '''
    Given a name that could be a module or a distribution, return the
    distribution.
    '''
    # Get latest info to find author, which is necessary for retrieving a
    # specific version
    try:
        with TmpDownload('{}/v0/module/{}'.format(cpan_url, module)) as json_path:
            with open(json_path, encoding='utf-8-sig') as dist_json_file:
                mod_dict = json.load(dist_json_file)
    # If there was an error, just assume module was a distribution
    except RuntimeError:
        distribution = module
    else:
        distribution = mod_dict['distribution']

    return distribution


def get_release_info(cpan_url, package, version):
    '''
    Return a dictionary of the JSON information stored at cpan.metacpan.org
    corresponding to the given package/dist/module.
    '''
    # Transform module name to dist name if necessary
    orig_package = package
    package = dist_for_module(cpan_url, package)
    if orig_package != package:
        print(("WARNING: %s was part of the %s distribution, so we are making" +
               " a recipe for the distribution instead.") % (orig_package,
                                                             package))
    package = package.replace('::', '-')

    # Get latest info to find author, which is necessary for retrieving a
    # specific version
    try:
        with TmpDownload('{}/v0/release/{}'.format(cpan_url, package)) as json_path:
            with open(json_path, encoding='utf-8-sig') as dist_json_file:
                rel_dict = json.load(dist_json_file)
    except RuntimeError:
        sys.exit(("Error: Could not find any versions of package %s on " +
                  "MetaCPAN.") % (orig_package))

    # If the latest isn't the version we're looking for, we have to do another
    # request
    if version is not None and rel_dict['version'] != version:
        author = rel_dict['author']
        try:
            with TmpDownload('{}/v0/release/{}/{}-{}'.format(cpan_url,
                                                             author,
                                                             package,
                                                             version)) as json_path:
                with open(json_path, encoding='utf-8-sig') as dist_json_file:
                    new_rel_dict = json.load(dist_json_file)
        except RuntimeError:
            sys.exit("Error: Version %s of %s is not available on MetaCPAN."
                      % (version, orig_package))

        rel_dict = new_rel_dict

    return rel_dict


def get_checksum_and_size(download_url):
    '''
    Looks in the CHECKSUMS file in the same directory as the file specified
    at download_url and returns the md5 hash and file size.
    '''
    base_url = dirname(download_url)
    filename = basename(download_url)
    with TmpDownload(base_url + '/CHECKSUMS') as checksum_path:
        with open(checksum_path) as checksum_file:
            found_file = False
            md5 = None
            size = None
            for line in checksum_file:
                line = line.strip()
                if line.startswith("'" + filename):
                    found_file = True
                elif found_file:
                    if line.startswith("'md5'"):
                        md5 = line.split("=>")[1].strip("', ")
                    elif line.startswith("'size"):
                        size = line.split("=>")[1].strip("', ")
                        break
                    # This should never happen, but just in case
                    elif line.startswith('}'):
                        break
    return md5, size


def perl_to_conda(name):
    ''' Sanitizes a Perl package name for use as a conda package name. '''
    return 'perl-' + name.replace('::', '-').lower()


