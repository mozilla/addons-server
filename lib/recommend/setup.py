from distutils.core import setup, Extension

m = Extension('_recommend', sources=['_recommend.c'])

setup(name='recommend', version='0.1', ext_modules=[m])
