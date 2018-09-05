#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright © 2018 Malcolm Ramsay <malramsay64@gmail.com>
#
# Distributed under terms of the MIT license.

"""Run an experiment varying a number of variables."""

import logging
import os
import shutil
import subprocess
import sys
from collections import ChainMap
from itertools import product
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Union

import click
import numpy as np
import yaml

from .commands import Command, Job
from .pbs import create_pbs_file

logger = logging.getLogger(__name__)
logger.setLevel("DEBUG")

# Type definitions
PathLike = Union[str, Path]
YamlValue = Union[str, int, float]
CommandInput = Union[str, Dict[str, YamlValue]]
VarType = Union[YamlValue, List[YamlValue], Dict[str, YamlValue]]
VarMatrix = List[Dict[str, YamlValue]]


def combine_dictionaries(dicts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge a list of dictionaries into a single dictionary.

    Where there are collisions the first value in the list will be set
    as this function is using ChainMap to combine the dicts.

    """
    return dict(ChainMap(*dicts))


def iterator_zip(variables: VarType, parent: str = None) -> Iterable[VarMatrix]:
    """Apply the zip operator to a set of variables.

    This uses the python zip iterator to combine multiple lists of variables such that
    the nth variable in each list is aligned.

    Args:
        variables: The variables object
        parent: Unused

    """

    logger.debug("Yielding from zip iterator")
    if isinstance(variables, list):
        for item in variables:
            yield list(variable_matrix(item, parent, "zip"))
    else:
        yield list(variable_matrix(variables, parent, "zip"))


def iterator_product(variables: VarType, parent: str = None) -> Iterable[VarMatrix]:
    """Apply the product operator to a set of variables.

    This uses the python itertools.product iterator to combine multiple variables
    such that all possible combinations are generated. This is the default iterator
    however this is a method of manually specifying the option.

    Args:
        variables: The variables object
        parent: Unused

    """
    logger.debug("Yielding from product iterator")
    if isinstance(variables, list):
        raise ValueError(f"Product only takes mappings of values, got {variables}")

    yield list(variable_matrix(variables, parent, "product"))


def iterator_combine(variables: VarType, parent: str = None) -> Iterable[VarMatrix]:
    """This performs a combination of zip and product operations.

    This takes a list of values over which the zip operator is applied, however the
    contents of each list item has the product iterator applied. This iterator is
    syntactic sugar for the nested use of the zip and product iterators.

    Args:
        variables: The variables object
        parent: Unused

    """
    logger.debug("Yielding from combine iterator")
    if not isinstance(variables, list):
        raise ValueError(
            f"Combine keyword only takes a list of arguments, got {variables}"
        )

    for item in variables:
        yield list(variable_matrix(item, parent, "product"))


def iterator_arange(variables: VarType, parent: str) -> Iterable[VarMatrix]:
    """Create a list of values using the numpy arange function.

    Args:
        variables: The input variables for the creation of the range
        parent: The variable for which the values are being generated.

    Returns: A list of dictionaries mapping the parent to each value.

    """
    assert parent is not None
    if isinstance(variables, (int, float)):
        yield [{parent: i} for i in np.arange(variables)]

    elif isinstance(variables, dict):
        if not variables.get("stop"):
            raise ValueError(f"Stop is a required keyword.")
        yield [{parent: i} for i in np.arange(**variables)]

    else:
        raise ValueError(
            f"The arange keyword only takes a dict as arguments, got {variables} of type {type(variables)}"
        )


def variable_matrix(
    variables: VarType, parent: str = None, iterator: str = "product"
) -> Iterable[Dict[str, YamlValue]]:
    """Process the variables into a list of the appropriate combinations.

    This function performs recursive processing of the input variables, creating an
    iterator which has all the combinations of variables specified in the input.

    """
    _iters: Dict[str, Callable] = {"product": product, "zip": zip}
    _special_keys: Dict[str, Callable[[VarType, Any], Iterable[VarMatrix]]] = {
        "zip": iterator_zip,
        "product": iterator_product,
        "arange": iterator_arange,
        "combine": iterator_combine,
    }

    if isinstance(variables, dict):
        key_vars: List[List[Dict[str, YamlValue]]] = []

        # Handling of specialised iterators
        for key, function in _special_keys.items():
            if variables.get(key):
                item = variables[key]
                assert item is not None
                for val in function(item, parent):
                    key_vars.append(val)

                if key == "combine":
                    iterator = "zip"
                del variables[key]

        for key, value in variables.items():
            key_vars.append(list(variable_matrix(value, key, iterator)))

        logger.debug("key vars: %s", key_vars)

        # Iterate through all possible products generating a dictionary
        for i in _iters[iterator](*key_vars):
            logger.debug("dicts: %s", i)
            yield combine_dictionaries(i)

    # Iterate through a list of values
    elif isinstance(variables, list):
        for item in variables:
            yield from variable_matrix(item, parent, iterator)

    # Stopping condition -> we have either a single value from a list
    # or a value had only one item
    else:
        assert parent is not None
        yield {parent: variables}


def uniqueify(my_list: Any) -> List[Any]:
    """Remove duplicate entries in a list retaining order."""
    if sys.version_info >= (3, 6):
        # An implementation specific detail of py3.6 is the retention of order
        # within a dictionary. In py3.7 this becomes the documented behaviour.
        return list(dict.fromkeys(my_list))

    # Slower method of order preserving unique list in older python versions
    seen = set()
    return [x for x in my_list if x not in seen and not seen.add(x)]


def process_jobs(
    jobs: List[Dict], matrix: VarMatrix, scheduler_options: Dict[str, Any] = None
) -> Iterator[Job]:
    assert jobs is not None

    logger.debug("Found %d jobs in file", len(jobs))

    for job in jobs:
        command = job.get("command")
        assert command is not None
        yield Job(process_command(command, matrix), scheduler_options)


def process_command(command: CommandInput, matrix: VarMatrix) -> List[Command]:
    """Generate all combinations of commands given a variable matrix.

    Processes the commands to be sequences of strings.

    """
    assert command is not None
    if isinstance(command, str):
        command_list = [Command(command, variables=variables) for variables in matrix]
    elif isinstance(command, list):
        command_list = [Command(command, variables=variables) for variables in matrix]
    else:
        if command.get("command") is not None:
            cmd = command.get("command")
        else:
            cmd = command.get("cmd")
        creates = str(command.get("creates", ""))
        requires = str(command.get("requires", ""))

        assert isinstance(cmd, (list, str))
        command_list = [
            Command(cmd, variables, creates, requires) for variables in matrix
        ]
    return uniqueify(command_list)


def _range_constructor(loader, node):
    """Support generating a list of values."""
    try:
        value = loader.construct_mapping(node)
    # Support passing just a single value
    except yaml.constructor.ConstructorError:
        value = loader.construct_scalar(node)
        if "." in value:
            value = float(value)
        else:
            try:
                value = int(value)
            except ValueError:
                raise yaml.constructor.ConstructorError(
                    "Invalid specification for arange."
                )
        return list(np.arange(value))

    if value.get("stop") is None:
        raise yaml.constructor.ConstructorError("arange tag needs a stop value")
    if value.get("start") is None:
        return list(
            np.arange(value["stop"], step=value.get("step"), dtype=value.get("dtype"))
        )
    return list(
        np.arange(
            value["start"],
            value["stop"],
            step=value.get("step"),
            dtype=value.get("dtype"),
        )
    )


def read_file(filename: PathLike = "experiment.yml") -> Dict[str, Any]:
    """Read and parse yaml file."""
    logger.debug("Input file: \n%s", filename)
    yaml.add_constructor("!arange", _range_constructor)

    with open(filename, "r") as stream:
        structure = yaml.load(stream)
    return structure


def process_structure(
    structure: Dict[str, Any], scheduler: str = "shell"
) -> Iterator[Job]:
    input_variables = structure.get("variables")
    if input_variables is None:
        raise KeyError('The key "variables" was not found in the input file.')
    assert isinstance(input_variables, Dict)

    # create variable matrix
    variables = list(variable_matrix(input_variables))
    assert variables

    scheduler_options = None

    # Check for pbs options
    if structure.get(scheduler):
        scheduler_options = structure.get(scheduler)
        if scheduler_options is True:
            scheduler_options = {}
        assert isinstance(scheduler_options, dict)
        if structure.get("name"):
            # set the name attribute in pbs to global name if no name defined in pbs
            scheduler_options.setdefault("name", structure.get("name"))

    jobs_dict = structure.get("jobs")
    if jobs_dict is None:
        input_command = structure.get("command")
        if isinstance(input_command, list):
            jobs_dict = [{"command": cmd} for cmd in input_command]
        else:
            jobs_dict = [{"command": input_command}]

    yield from process_jobs(jobs_dict, variables, scheduler_options)


def run_jobs(
    jobs: Iterator[Job], scheduler: str = "shell", directory=Path.cwd()
) -> None:
    if scheduler == "shell":
        run_bash_jobs(jobs, directory)
    elif scheduler == "pbs":
        run_pbs_jobs(jobs, directory)
    else:
        raise ValueError(
            f"Scheduler '{scheduler}'was not recognised. Possible values are ['shell', 'pbs']"
        )


def run_bash_jobs(jobs: Iterator[Job], directory: PathLike = Path.cwd()) -> None:
    """Submit commands to the bash shell.

    This function runs the commands iteratively but handles errors in the
    same way as with the pbs_commands function. A command will run for all
    combinations of variables in the variable matrix, however if any one of
    those commands fails then the next command will not run.

    """
    logger.debug("Running commands in bash shell")
    # iterate through command groups
    for job in jobs:
        # Check shell exists
        if shutil.which(job.shell) is None:
            raise ProcessLookupError("The shell '{job.shell}' was not found.")

        failed = False
        for command in job:
            for cmd in command:
                logger.info(cmd)
                result = subprocess.run([job.shell, "-c", f"{cmd}"], cwd=str(directory))
                if result.returncode != 0:
                    failed = True
                    logger.error("Command failed: %s", command)
                    break
        if failed:
            logger.error("A command failed, not continuing further.")
            return


def run_pbs_jobs(
    jobs: Iterator[Job], directory: PathLike = Path.cwd(), basename: str = "experi"
) -> None:
    """Submit a series of commands to a batch scheduler.

    This takes a list of strings which are the contents of the pbs files, writes the
    files to disk and submits the job to the scheduler. Files which match the pattern of
    the resulting files <basename>_<index>.pbs are deleted before writing the new files.

    To ensure that commands run consecutively the aditional requirement to the run
    script `-W depend=afterok:<prev_jobid>` is added. This allows for all the components
    of the experiment to be conducted in a single script.

    Note: Running this function requires that the command `qsub` exists, implying that a
    job scheduler is installed.

    """
    submit_job = True
    logger.debug("Creating commands in pbs files.")
    # Check qsub exists
    if shutil.which("qsub") is None:
        logger.warning(
            "The `qsub` command is not found."
            "Skipping job submission and just generating files"
        )
        submit_job = False

    # Ensure directory is a Path
    directory = Path(directory)

    # remove existing files
    for fname in directory.glob(basename + "*.pbs"):
        print("Removing {}".format(fname))
        os.remove(str(fname))

    # Write new files and generate commands
    prev_jobids: List[str] = []
    for index, job in enumerate(jobs):
        # Generate pbs file
        content = create_pbs_file(job)
        # Write file to disk
        fname = Path(directory / "{}_{:02d}.pbs".format(basename, index))
        with fname.open("w") as dst:
            dst.write(content)

        if submit_job:
            # Construct command
            submit_cmd = ["qsub"]

            if prev_jobids:
                # Continue to append all previous jobs to submit_cmd so subsequent jobs die along
                # with the first.
                submit_cmd += ["-W", "depend=afterok:{} ".format(":".join(prev_jobids))]

            # acutally run the command
            logger.info(str(submit_cmd))
            try:
                cmd_res = subprocess.check_output(
                    submit_cmd + [fname.name], cwd=str(directory)
                )
            except subprocess.CalledProcessError:
                logger.error("Submitting job to the queue failed.")
                break

            prev_jobids.append(cmd_res.decode().strip())


def process_scheduler(structure: Dict[str, Any]) -> str:
    """Get the scheduler to run the jobs.

    Determine the shell to run the command from the input file. This checks for the
    presence of keys in the input file corresponding to the different schedulers. The
    schedulers that are supported are

    - shell, and
    - pbs

    listed in the order of precedence. The first scheduler with a truthy value in the
    input file is the value returned by this function. Where no truthy values are found
    the defualt value is "shell.

    """
    if structure.get("shell"):
        return "shell"
    if structure.get("pbs"):
        return "pbs"
    return "shell"


def _set_verbosity(ctx, param, value):
    if value == 1:
        logging.basicConfig(level=logging.INFO)
    if value == 2:
        logging.basicConfig(level=logging.DEBUG)


@click.command()
@click.version_option()
@click.option(
    "-f",
    "--input-file",
    type=click.Path(exists=True, dir_okay=False),
    default="experiment.yml",
)
@click.option(
    "-v", "--verbose", callback=_set_verbosity, expose_value=False, count=True
)
def main(input_file) -> None:
    # Process and run commands
    input_file = Path(input_file)
    structure = read_file(input_file)
    scheduler = process_scheduler(structure)
    jobs = process_structure(structure, scheduler)
    run_jobs(jobs, scheduler, input_file.parent)
