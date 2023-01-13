import inspect
import typing


def _conv(ann, v):
    if ann is inspect._empty:
        return v
    if ann is bool:
        return v.lower() in ["on", "yes", "true"]
    return v


class ArgException(Exception):
    pass


def args_for_func(func, raw_args):
    sig = inspect.Signature.from_callable(func)
    sig = sig.replace(parameters=list(sig.parameters.values())[1:])
    params = sig.parameters
    param_list = list(params.values())
    kw = {}
    if param_list and param_list[-1].annotation == typing.List[str]:
        last_arg_name = param_list[-1].name
    else:
        last_arg_name = None
    for i, a in enumerate(raw_args):
        if i >= len(param_list):
            if last_arg_name is None:
                raise ArgException("too many arguments")
            kw.setdefault(last_arg_name, []).append(a)
        else:
            p = param_list[i]
            if p.name == last_arg_name:
                kw[p.name] = [a]
                continue
            if p.name in kw:
                raise ArgException(f"multiple values for {p.name}")
            kw[p.name] = _conv(p.annotation, a)
    return kw


def parse(actions, raw_args):
    calls = []

    func = None
    func_args = []

    def dispatch():
        if func is None:
            if func_args:
                1/0
        else:
            try:
                kw = args_for_func(func, func_args)
            except ArgException as e:
                e.args = (func.__name__.replace('_', '-') + ": " + str(e),)
                raise
            calls.append((func, kw))
            func_args[:] = []

    for a in raw_args:
        if a.startswith('--'):
            dispatch()
            a = a[2:]
            try:
                func = actions[a]
            except AttributeError:
                raise ArgException(f"unknown action {a!r}")
        elif func is None:
            raise ArgException(f"no action specified for {a!r}")
        else:
            func_args.append(a)

    dispatch()

    return calls
