import sys
import bokeh

if sys.platform != 'win32':
    bokeh.test(verbosity=2, exit=False)

print('bokeh.__version__: %s' % bokeh.__version__)
#assert bokeh.__version__ == '0.7.1'
