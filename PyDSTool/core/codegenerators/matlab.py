#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function

from copy import deepcopy

from PyDSTool.common import intersect, concatStrDict, idfn
from PyDSTool.parseUtils import addArgToCalls
from PyDSTool.Symbolic import QuantSpec

from .base import _processReused, CodeGenerator


MATLAB_FUNCTION_TEMPLATE = """\
function [vf_, y_] = {name}(vf_, t_, x_, p_)
% Vector field definition for model {specname}
% Generated by PyDSTool for ADMC++ target

{pardef}{vardef}
{start}{reuseterms}
{result}

{end}
"""


MATLAB_AUX_TEMPLATE = """\
function y_ = {name}({args},  p_)
% Auxilliary function {name} for model {specname}
% Generated by PyDSTool for ADMC++ target

{pardef} \


{reuseterms}
y_ = {result};

"""


class Matlab(CodeGenerator):
    def __init__(self, fspec, **kwargs):
        if "define" not in kwargs:
            kwargs["define"] = "\t{0} = {1}_({2});\n"

        if "power_sign" not in kwargs:
            kwargs["power_sign"] = "^"

        super(Matlab, self).__init__(fspec, **kwargs)

        before = "% Verbose code insert -- begin "
        after = "% Verbose code insert -- end \n\n"

        self.context = {
            "specname": self.fspec.name,
            "pardef": "\n% Parameter definitions\n\n"
            + self.defineMany(self.fspec.pars, "p", 1),
            "vardef": "\n% Variable definitions\n\n"
            + self.defineMany(self.fspec.vars, "x", 1),
            "start": self._format_code(self.opts["start"], before, after),
            "end": self._format_code(self.opts["end"], before, after),
        }

        self.reuse = "% reused term definitions \n{0}\n"
        self._endstatementchar = ";"

    def generate_auxfun(self, name, auxspec):
        namemap = dict((v, v + "__") for v in auxspec[0])
        specupdated, reusestr = self.prepare_spec({name: auxspec[1]}, namemap=namemap)
        reusestr = _map_names(reusestr, namemap)
        context = {
            "name": name,
            "args": ", ".join([namemap[v] for v in auxspec[0]]),
            "reuseterms": "\n" + self.reuse.format(reusestr.strip())
            if reusestr
            else "",
            "result": specupdated[name],
        }

        code = self._render(MATLAB_AUX_TEMPLATE, context)
        return code, "\n".join(code.split("\n")[:5])

    def _render(self, template, context):
        self.context.update(context)
        return template.format(**self.context)

    def prepare_spec(self, specdict, **kwargs):
        prepared = deepcopy(specdict)
        if hasattr(self, "preprocess_hook"):
            prepared = self.preprocess_hook(prepared, **kwargs)

        reused, processed, reuseterms, order = _processReused(
            list(prepared.keys()),
            prepared,
            self.fspec.reuseterms,
            getattr(self, "_indentstr", ""),
            getattr(self, "_typestr", ""),
            getattr(self, "_endstatementchar", ""),
            self.adjust_call,
        )
        self.fspec._protected_reusenames = reuseterms

        if hasattr(self, "postprocess_hook"):
            processed = self.postprocess_hook(processed, **kwargs)

        return processed, _generate_reusestr(reused, reuseterms, order)

    def preprocess_hook(self, specdict, **__):
        processed = deepcopy(specdict)
        for name, spec in processed.items():
            processed[name] = self._normalize_spec(spec)
        return processed

    def postprocess_hook(self, specdict, **kwargs):
        namemap = kwargs.get("namemap", {})
        processed = deepcopy(specdict)
        for name, spec in processed.items():
            spec = _map_names(spec, namemap)
            processed[name] = self.adjust_call(spec)
        return processed

    @property
    def adjust_call(self):
        """Callable which adds parameter argument to auxiliary function calls (if any)"""
        if self.fspec._auxfnspecs:
            return lambda s: addArgToCalls(s, list(self.fspec._auxfnspecs.keys()), "p_")
        return idfn

    def generate_spec(self, specname_vars, specs):
        name = "vfield"
        specupdated, reusestr = self.prepare_spec(
            dict((v, specs[v]) for v in specname_vars)
        )

        context = {
            "name": name,
            "result": "\n".join(
                [
                    "y_({0}) = {1};".format(i + 1, specupdated[it])
                    for i, it in enumerate(specname_vars)
                ]
            ),
            "reuseterms": self.reuse.format(reusestr.strip()) if reusestr else "",
        }

        code = self._render(MATLAB_FUNCTION_TEMPLATE, context)
        return (code, name)

    def _process_builtins(self, specStr):
        # NEED TO CHECK WHETHER THIS IS NECESSARY AND WORKS
        # IF STATEMENTS LOOK DIFFERENT IN MATLAB
        qspec = QuantSpec("spec", specStr)
        qtoks = qspec[:]
        if "if" in qtoks:
            raise NotImplementedError
        else:
            new_specStr = specStr
        return new_specStr


def _generate_reusestr(reused, reuseterms, order):
    """Build string with reused term definitions from data returned by `_processReused`"""
    reusedefs = {}.fromkeys(reuseterms)
    for deflist in reused.values():
        for d in deflist:
            reusedefs[d[2]] = d

    return concatStrDict(reusedefs, intersect(order, reusedefs.keys()))


def _map_names(spec, namemap):
    if spec and namemap:
        q = QuantSpec("__temp__", spec, preserveSpace=True)
        q.mapNames(namemap)
        spec = q()
    return spec
