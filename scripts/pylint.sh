VENV=$WORKSPACE/venv
source $VENV/bin/activate
PYTHONPATH='$WORKSPACE/..'
pylint --rcfile scripts/pylintrc -f parseable $WORKSPACE > pylint.txt
echo "pylint complete"
