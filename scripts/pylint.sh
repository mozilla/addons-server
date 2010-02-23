#!/bin/bash
VENV=$WORKSPACE/venv
source $VENV/bin/activate
export PYTHONPATH="$WORKSPACE/..:$WORKSPACE/apps:$WORKSPACE/lib"
pylint --rcfile scripts/pylintrc > pylint.txt
echo "pylint complete"
