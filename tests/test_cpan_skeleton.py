from textwrap import dedent

import pytest

from conda_build.config import Config
from conda_build.skeletons import cpan


@pytest.mark.parametrize('module,perl_version,config,corelist_mock_outputs,expected',
        [
            ('List::Util',
             None,
             Config(variant={'perl': '5.26.0'}),
             [
                 "List::Util 1.46_02\n",
                 dedent("""
                    Data for 2018-04-14
                    List::Util was first released with perl v5.7.3
                    """.lstrip())
             ],
             '1.46_02',
             ),
            ('List::Util',
             '5.15.0',
             Config(variant={'perl': '5.26.0'}),
             [
                 "List::Util 1.23\n",
                 dedent("""
                    Data for 2018-04-14
                    List::Util was first released with perl v5.7.3
                    """.lstrip())
             ],
             '1.23',
             ),
            ('Sys::Syslog::Win32',
             None,
             Config(variant={'perl': '5.26.0'}),
             [
                 "Sys::Syslog::Win32 undef\n",
                 dedent("""
                    Data for 2018-04-14
                    Sys::Syslog::Win32 was first released with perl v5.15.1
                    """.lstrip())
             ],
             '5.26.0',
             ),
            ('Sys::Syslog::Win32',
             '5.15.0',
             Config(variant={'perl': '5.26.0'}),
             [
                 "Sys::Syslog::Win32 undef\n",
                 dedent("""
                    Data for 2018-04-14
                    Sys::Syslog::Win32 was first released with perl v5.15.1
                    """.lstrip())
             ],
             None,
             ),
            ('LWP',
             None,
             Config(variant={'perl': '5.26.0'}),
             [
                 "LWP undef\n",
                 dedent("""
                    LWP was not in CORE (or so I think)
                    """.lstrip())
             ],
             None,
             ),
        ],
        ids=[
                'simple_in_core',
                'pv_param_wins',
                'undef_after_in_core',
                'undef_before_in_core',
                'not_in_core',
             ])
def test_core_model_version(module, perl_version, config, corelist_mock_outputs, expected, mocker):
    check_output = mocker.patch('subprocess.check_output')
    check_output.side_effect = corelist_mock_outputs

    cmv = cpan.core_module_version(module, perl_version, config)
    check_output.assert_called()
    assert(cmv == expected)
