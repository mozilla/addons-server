VENV=$WORKSPACE/venv
source $VENV/bin/activate
PYTHONPATH="$WORKSPACE/..:$WORKSPACE/apps:$WORKSPACE/lib"
pylint --rcfile scripts/pylintrc $WORKSPACE > pylint.txt
echo "pylint complete"
