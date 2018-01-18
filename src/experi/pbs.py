#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright © 2018 Malcolm Ramsay <malramsay64@gmail.com>
#
# Distributed under terms of the MIT license.

"""Generate pbs files for submission on batch systems.

This will generate a .pbs file with all the information required to run a single command from the
list of commands. The variables will be generated and iterated over using the job array feature of
pbs.
"""

from typing import Any, List, Union, Mapping
from collections import ChainMap


PBS_FILE = """#!/bin/bash
#PBS -N {name}
#PBS -l select={nodes}:ncpus={cpus}:memory={memory}
#PBS -l walltime={walltime}
#PBS -J {num_jobs}

cd "$PBS_O_WORKDIR"
{setup}

COMMAND={command_list}

"${{COMMAND[$PBS_ARRAY_INDEX]}}"
"""


def commands2bash_array(command_group: List[str]) -> str:
    """Convert the list of commands to a bash array."""
    return_string = '('
    for command in command_group:
        return_string += '"' + command + '" \\\n'
    return_string += ')'
    return return_string


def parse_setup(options: Union[List, str]) -> str:
    """Convert potentially a list of commands into a single string.

    This creates a single string with newlines between each element of the list
    so that they will all run after each other in a bash script.

    """
    if isinstance(options, str):
        return options
    return '\n'.join(options)


def create_pbs_file(command_group: List[str],
                    pbs_options: Mapping[str, Any]) -> str:
    """Substitute values into a template pbs file.

    This substitues the values in the pbs section of the input file
    into a simple template pbs file. Values not specified will use
    default options.

    """
    default_options = {
        'walltime': '1:00',
        'cpus': '1',
        'nodes': '1',
        'memory': '4gb',
        'name': 'experi',
        'setup': '',
    }
    pbs_options = ChainMap(pbs_options, default_options)
    pbs_options['setup'] = parse_setup(pbs_options['setup'])

    return PBS_FILE.format(**pbs_options,
                           num_jobs=len(command_group),
                           command_list=commands2bash_array(command_group))
