"""Utilities for writing overlays."""

from pytype import abstract
from pytype import class_mixin
from pytype import function
from pytype.pytd import pytd
from pytype.typegraph import cfg


# Various types accepted by the annotations dictionary.
# Runtime type checking of annotations, since if we do have an unexpected type
# being stored in annotations, we should catch that as soon as possible, and add
# it to the list if valid.
PARAM_TYPES = (
    cfg.Variable,
    class_mixin.Class,
    abstract.TypeParameter,
    abstract.Union,
    abstract.Unsolvable,
)


class Param:
  """Internal representation of method parameters."""

  def __init__(self, name, typ=None, default=None):
    if typ:
      assert isinstance(typ, PARAM_TYPES), (typ, type(typ))
    self.name = name
    self.typ = typ
    self.default = default

  def unsolvable(self, vm, node):
    """Replace None values for typ and default with unsolvable."""
    self.typ = self.typ or vm.convert.unsolvable
    self.default = self.default or vm.new_unsolvable(node)
    return self

  def __repr__(self):
    return "Param(%s, %r, %r)" % (self.name, self.typ, self.default)


def make_method(vm, node, name, params=None, kwonly_params=None,
                return_type=None, self_param=None, varargs=None, kwargs=None,
                kind=pytd.MethodTypes.METHOD):
  """Make a method from params.

  Args:
    vm: vm
    node: Node to create the method variable at
    name: The method name
    params: Positional params [type: [Param]]
    kwonly_params: Keyword only params [type: [Param]]
    return_type: Return type [type: PARAM_TYPES]
    self_param: Self param [type: Param, defaults to self: Any]
    varargs: Varargs param [type: Param, allows *args to be named and typed]
    kwargs: Kwargs param [type: Param, allows **kwargs to be named and typed]
    kind: The method kind

  Returns:
    A new method wrapped in a variable.
  """

  def _process_annotation(param):
    """Process a single param into annotations."""
    if not param.typ:
      return
    elif isinstance(param.typ, cfg.Variable):
      if all(t.cls for t in param.typ.data):
        types = param.typ.data
        if len(types) == 1:
          annotations[param.name] = types[0].cls
        else:
          t = abstract.Union([t.cls for t in types], vm)
          annotations[param.name] = t
    else:
      annotations[param.name] = param.typ

  # Set default values
  params = params or []
  kwonly_params = kwonly_params or []
  if kind in (pytd.MethodTypes.METHOD, pytd.MethodTypes.PROPERTY):
    self_param = [self_param or Param("self", None, None)]
  elif kind == pytd.MethodTypes.CLASSMETHOD:
    self_param = [Param("cls", None, None)]
  else:
    assert kind == pytd.MethodTypes.STATICMETHOD
    self_param = []
  annotations = {}

  params = self_param + params

  return_param = Param("return", return_type, None) if return_type else None
  special_params = [x for x in (return_param, varargs, kwargs) if x]
  for param in special_params + params + kwonly_params:
    _process_annotation(param)

  names = lambda xs: tuple(x.name for x in xs)
  param_names = names(params)
  kwonly_names = names(kwonly_params)
  defaults = {x.name: x.default for x in params + kwonly_params if x.default}
  varargs_name = varargs.name if varargs else None
  kwargs_name = kwargs.name if kwargs else None

  ret = abstract.SimpleFunction(
      name=name,
      param_names=param_names,
      varargs_name=varargs_name,
      kwonly_params=kwonly_names,
      kwargs_name=kwargs_name,
      defaults=defaults,
      annotations=annotations,
      vm=vm)

  # Check that the constructed function has a valid signature
  bad_param = ret.signature.check_defaults()
  if bad_param:
    msg = "In method %s, non-default argument %s follows default argument" % (
        name, bad_param)
    vm.errorlog.invalid_function_definition(vm.frames, msg)

  retvar = ret.to_variable(node)
  if kind in (pytd.MethodTypes.METHOD, pytd.MethodTypes.PROPERTY):
    return retvar
  if kind == pytd.MethodTypes.CLASSMETHOD:
    decorator = vm.load_special_builtin("classmethod")
  else:
    assert kind == pytd.MethodTypes.STATICMETHOD
    decorator = vm.load_special_builtin("staticmethod")
  args = function.Args(posargs=(retvar,))
  return decorator.call(node, funcv=None, args=args)[1]
