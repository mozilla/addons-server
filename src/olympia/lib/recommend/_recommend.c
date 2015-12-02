#include <Python.h>

PyObject *array, *ArrayType;

/* Specialized _symmetric_diff_count for array.array() objects.
 * We get to skip all the GC and rich comparison functions since array()
 * stores C types directly.
 *
 * This calculates len(set(xs).symmetric_difference(ys)) without the
 * extra data structures in between. xs and ys must be sorted in
 * ascending order for the algorithm to work.
 */
static Py_ssize_t
array_symmetric_diff_count(PyListObject *a, PyListObject *b) {
    Py_ssize_t i, j, rv = 0;
    long x, y;
    /* Exploit the ascending sort of both lists and traverse both arrays
     * together, moving the pointer of the iterator with the smaller
     * value. Leftovers are picked up after the loop.
     */
    for (i = 0, j = 0; i < Py_SIZE(a) && j < Py_SIZE(b);) {
        x = a->ob_item[i], y = b->ob_item[j];
        if (x < y) {
            rv++;
            i++;
        } else if (x > y ) {
            rv++;
            j++;
        } else {
            i++;
            j++;
        }
    }
    if (i < Py_SIZE(a)) {
        rv += Py_SIZE(a) - i;
    } else if (j < Py_SIZE(b)) {
        rv += Py_SIZE(b) - j;
    }
    return rv;
}


/* Generalized version of array_symmetric_diff_count for Python objects. */
static Py_ssize_t
_symmetric_diff_count(PyObject *self, PyObject *args) {
    PyListObject *a, *b;
    PyObject *xs, *ys, *x, *y;
    Py_ssize_t rv = 0;
    int cmp, cnt=0;

    /* Parse arguments and get iterators. */
    if (!PyArg_ParseTuple(args, "OO", &a, &b))
        return -1;

    if (PyObject_IsInstance(a, ArrayType) &&
        PyObject_IsInstance(b, ArrayType)) {
        return array_symmetric_diff_count(a, b);
    }

    xs = PyObject_GetIter(a);
    ys = PyObject_GetIter(b);
    if (xs == NULL || ys == NULL){
        Py_XDECREF(xs);
        Py_XDECREF(ys);
        return -1;
    }

    x = PyIter_Next(xs);
    y = PyIter_Next(ys);
    while (1) {
        if (x == NULL) {
            Py_DECREF(xs);
            /* Swap the names so we can share the final loop. */
            x = y;
            xs = ys;
            break;
        } else if (y == NULL) {
            Py_DECREF(ys);
            break;
        }
        cmp = PyObject_Compare(x, y);
        if (cmp == -1) {
            Py_DECREF(x);
            x = PyIter_Next(xs);
            rv++;
        } else if (cmp == 1) {
            Py_DECREF(y);
            y = PyIter_Next(ys);
            rv++;
        } else {
            Py_DECREF(x);
            Py_DECREF(y);
            x = PyIter_Next(xs);
            y = PyIter_Next(ys);
        }
    }
    /* xs and x are the only PyObjects left. */
    if (PyErr_Occurred()) {
        Py_DECREF(x); Py_DECREF(xs);
        return -1;
    }
    while (x != NULL) {
        rv++;
        Py_DECREF(x);
        x = PyIter_Next(xs);
    }
    Py_DECREF(xs);
    return rv;
}


/* A wrapper around _symmetric_diff_count so this is available for
 * testing.
 */
static PyObject *
symmetric_diff_count(PyObject *self, PyObject *args) {
    Py_ssize_t rv = _symmetric_diff_count(self, args);
    if (rv == -1)
        return rv;
    return PyInt_FromLong(rv);
}


/* Calculate the similarity through a simple euclidean distance. */
static PyObject *
similarity(PyObject *self, PyObject *args) {
    Py_ssize_t diff = _symmetric_diff_count(self, args);
    double rv = 1. / (1. + diff);
    return PyFloat_FromDouble(rv);
}


static PyMethodDef
recommend_methods[] = {
    {"symmetric_diff_count", symmetric_diff_count, METH_VARARGS,
     "symmetric_diff_count(list1, list2)\n\
      \n\
      Count the number of items that are in exactly one of the lists.\n\
      Both lists are expected to be sorted in ascending order.\n"},
    {"similarity", similarity, METH_VARARGS,
     "similarity(list1, list2)\n\
      \n\
      Get a correlation coefficient between the two lists, calculated as\n\
      1. / (1. + symmetric_diff_count(list1, list2)\n"},
    {NULL, NULL, 0, NULL}
};


PyMODINIT_FUNC
init_recommend(void) {
    (void) Py_InitModule("_recommend", recommend_methods);
    array = PyImport_ImportModule("array");
    ArrayType = PyObject_GetAttrString(array, "array");
}
