
# Dynamic import of all modules in this package
import importlib
import pkgutil

package = __name__  # 'data.features'
package_path = __path__  # path to this folder

for _, modname, _ in pkgutil.iter_modules(package_path):
    importlib.import_module(f"{package}.{modname}")

# At this point, all modules have been imported,
# so all Feature subclasses are registered in Feature.REGISTRY
