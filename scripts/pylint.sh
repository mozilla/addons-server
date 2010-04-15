#!/bin/bash
VENV=$WORKSPACE/venv
source $VENV/bin/activate
export PYTHONPATH="$WORKSPACE/..:$WORKSPACE/apps:$WORKSPACE/lib"
pylint --rcfile scripts/pylintrc $WORKSPACE 2>/dev/null > pylint.txt
echo "pylint complete"
