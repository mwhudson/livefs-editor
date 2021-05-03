import inspect
import typing


def _conv(ann, v):
    if ann is inspect._empty:
        return v
    if ann is bool:
        return v.lower() in ["on", "yes", "true"]
    origin = getattr(ann, '__origin__', None)
    if origin in [typing.List, list]:
        arg = ann.__args__[0]
        return [_conv(arg, vv) for vv in v.split(',')]
    return v


def args_for_func(func, raw_args):
    sig = inspect.Signature.from_callable(func)
    sig = sig.replace(parameters=list(sig.parameters.values())[1:])
    params = sig.parameters
    param_list = list(params.values())
    args = []
    kw = {}
    for p in param_list:
        if p.kind == p.VAR_POSITIONAL:
            var_ann = p.annotation
    for i, a in enumerate(raw_args):
        if '=' in a:
            k, v = a.split('=')
            kw[k] = _conv(params[k].annotation, v)
        else:
            v = a
            if i >= len(param_list):
                ann = var_ann
            else:
                ann = param_list[i].annotation
            args.append(_conv(ann, v))
    sig.bind(*args, **kw)
    return (args, kw)


def parse(action_mod, raw_args):

    calls = []

    func = None
    func_args = []

    def dispatch():
        if func is None:
            if func_args:
                1/0
        else:
            args, kw = args_for_func(func, func_args)
            calls.append((func, args, kw))
            func_args[:] = []

    for a in raw_args:
        if a.startswith('--'):
            dispatch()
            func = getattr(action_mod, a[2:].replace('-', '_'))
        elif func is None:
            1/0
        else:
            func_args.append(a)

    dispatch()

    return calls
