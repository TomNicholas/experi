#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright © 2018 Malcolm Ramsay <malramsay64@gmail.com>
#
# Distributed under terms of the MIT license.

"""Test the building of pbs files."""

import pytest

from experi.commands import Command, Job
from experi.pbs import create_scheduler_file
from experi.run import process_structure, read_file, run_jobs

DEFAULT_PBS = """#!/bin/bash
#PBS -N Experi_Job
#PBS -l select=1:ncpus=1
#PBS -l walltime=1:00
PBS_ARRAY_INDEX=0

cd "$PBS_O_WORKDIR"


COMMAND=( \\
"echo 1" \\
)

${COMMAND[$PBS_ARRAY_INDEX]}
"""

DEFAULT_SLURM = """#!/bin/bash
#SBATCH --name Experi_Job
#SBATCH --cpus-per-task 1
#SBATCH --time 1:00
SLURM_ARRAY_TASK_ID=0

cd "$SLURM_SUBMIT_DIR"


COMMAND=( \\
"echo 1" \\
)

${COMMAND[$SLURM_ARRAY_TASK_ID]}
"""

@pytest.mark.parametrize(
    "job, result",
    [
        (Job([Command("echo 1")]), '( \\\n"echo 1" \\\n)'),
        (
            Job([Command("echo 1"), Command("echo 2")]),
            '( \\\n"echo 1" \\\n"echo 2" \\\n)',
        ),
    ],
    ids = ["single", "list"]
)
def test_jobs_as_bash_array(job, result):
    assert job.as_bash_array() == result



@pytest.mark.parametrize('scheduler, expected', [('pbs', DEFAULT_PBS), ('slurm', DEFAULT_SLURM)], ids=["PBS", "SLURM"])
def test_default_files(scheduler, expected):
    assert create_scheduler_file(scheduler, Job([Command("echo 1")])) == expected


def test_pbs_creation(tmp_dir):
    structure = read_file("test/data/pbs/experiment.yml")
    jobs = process_structure(structure, scheduler="pbs")
    run_jobs(jobs, "pbs", tmp_dir)
    expected = structure["result"]
    with (tmp_dir / "experi_00.pbs").open("r") as result:
        assert result.read().strip() == expected.strip()
