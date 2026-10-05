"""Share identical helpers without changing arithmetic or precision."""
from .bakeplan import Var


def optimize_plan(plan):
    before_nodes = len(plan.nodes)
    before_vars = sum(len(n.vars) for n in plan.nodes)
    aliases, signatures, nodes = {}, {}, []
    protected = set(plan.shape_props.values())
    for node in plan.nodes:
        node.vars = [Var(v.name, v.kind, aliases.get(v.ref, v.ref) if v.kind == 'prop' else v.ref, v.index)
                     for v in node.vars]
        if node.target[0] == 'prop' and node.target[1] not in protected:
            signature = (node.dtype, node.expr, tuple(node.vars))
            if signature in signatures:
                aliases[node.target[1]] = signatures[signature]
                continue
            signatures[signature] = node.target[1]
        nodes.append(node)
    plan.nodes = nodes
    ordered = [n.target[1] for n in nodes if n.target[0] == 'prop']
    seen = set(ordered) | set(aliases)
    ordered.extend(p for p in plan.props if p not in seen)
    plan.props = {name: plan.props[name] for name in ordered}
    plan.stats.update(nodes=len(nodes), properties=len(plan.props),
        optimized_drivers=before_nodes-len(nodes),
        optimized_variables=before_vars-sum(len(n.vars) for n in nodes))
    return plan
