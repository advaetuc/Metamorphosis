"""Batched native Geometry Nodes evaluator for the body scalar graph.

Each dependency level evaluates independent points. The expression shapes are
shared; per-point constants and input indices retain every authored coefficient.
No Python code executes during animation or when reopening a saved character.
"""
import ast
import bpy

SCALE=10000.0


def realize(graph,collection,prefix,raw_names,rig):
    signatures={};records={};levels=[0]*len(raw_names);batches={}
    for index,(expression,inputs) in enumerate(graph.nodes[len(raw_names):],len(raw_names)):
        constants=[]
        class Constants(ast.NodeTransformer):
            def visit_Constant(self,node):
                slot=len(constants);constants.append(float(node.value))
                return ast.Name(id='k'+str(slot),ctx=ast.Load())
        tree=Constants().visit(ast.parse(expression,mode='eval'))
        key=ast.dump(tree)
        if key not in signatures:signatures[key]=(len(signatures),tree.body)
        records[index]=(signatures[key][0],inputs,constants)
        level=1+max((levels[i] for i in inputs),default=0)
        levels.append(level);batches.setdefault(level,[]).append(index)
    order=list(range(len(raw_names)))+[i for batch in batches.values() for i in batch]
    lookup={i:slot for slot,i in enumerate(order)}
    owned=[]

    def mesh(role,count):
        data=bpy.data.meshes.new(prefix+'_'+role);data.vertices.add(count)
        obj=bpy.data.objects.new(data.name,data);collection.objects.link(obj)
        obj['mm_body_helper']=data['mm_body_helper']=True
        obj.hide_render=True;obj.hide_set(True)
        owned.append(obj);return obj

    def attr(obj,name,kind,values):
        obj.data.attributes.new(name,kind,'POINT').data.foreach_set('value',values)

    source=mesh('BODY_INPUT',len(raw_names))
    for index,name in enumerate(raw_names):
        bone,axis=name.rsplit('.',1)
        d=source.data.driver_add(f'vertices[{index}].co',0).driver
        v=d.variables.new();v.name='raw';v.type='TRANSFORMS'
        target=v.targets[0];target.id=rig;target.bone_target=bone
        target.transform_type='ROT_'+axis[-1].upper()
        target.rotation_mode='QUATERNION';target.transform_space='LOCAL_SPACE'
        d.expression='raw*10000'
    max_inputs=max(len(r[1]) for r in records.values())
    vms={}
    def vm_for(codes):
        codes=tuple(sorted(codes))
        if codes in vms:return vms[codes]
        vm=bpy.data.node_groups.new(prefix+'_BODY_EQUATIONS_'+str(len(vms)),'GeometryNodeTree')
        vm['mm_body_helper']=True
        for name in ('Geometry','Previous'):
            vm.interface.new_socket(name=name,in_out='INPUT',socket_type='NodeSocketGeometry')
        vm.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
        node,link=vm.nodes.new,vm.links.new
        inlet=node('NodeGroupInput');outlet=node('NodeGroupOutput')
    
        def attach(value,socket):
            if isinstance(value,(int,float)):socket.default_value=float(value)
            else:link(value,socket)
    
        def mathop(op,*args):
            n=node('ShaderNodeMath');n.operation=op
            for value,socket in zip(args,n.inputs):attach(value,socket)
            return n.outputs[0]
    
        def named(name,kind='FLOAT'):
            n=node('GeometryNodeInputNamedAttribute');n.data_type=kind
            n.inputs['Name'].default_value=name
            return n.outputs['Attribute']
    
        xyz=node('ShaderNodeSeparateXYZ');pos=node('GeometryNodeInputPosition')
        link(pos.outputs[0],xyz.inputs[0]);unscaled=mathop('DIVIDE',xyz.outputs['X'],SCALE)
        variables={}
        max_inputs=max(len(r[1]) for r in records.values())
        for i in range(max_inputs):
            n=node('GeometryNodeSampleIndex');n.data_type='FLOAT';n.domain='POINT'
            link(inlet.outputs['Previous'],n.inputs['Geometry'])
            link(unscaled,n.inputs['Value']);link(named('n'+str(i),'INT'),n.inputs['Index'])
            variables[chr(97+i)]=n.outputs['Value']
        for i in range(max(len(r[2]) for r in records.values())):variables['k'+str(i)]=named('k'+str(i))
        operations={ast.Add:'ADD',ast.Sub:'SUBTRACT',ast.Mult:'MULTIPLY',ast.Div:'DIVIDE'}
        functions={'min':'MINIMUM','max':'MAXIMUM','sqrt':'SQRT','sin':'SINE','cos':'COSINE','acos':'ARCCOSINE','exp':'EXPONENT','abs':'ABSOLUTE'}
        cache={}
        def expression(tree):
            key=ast.dump(tree)
            if key in cache:return cache[key]
            if isinstance(tree,ast.Name):value=variables[tree.id]
            elif isinstance(tree,ast.BinOp):value=mathop(operations[type(tree.op)],expression(tree.left),expression(tree.right))
            elif isinstance(tree,ast.UnaryOp) and isinstance(tree.op,ast.USub):value=mathop('MULTIPLY',expression(tree.operand),-1)
            elif isinstance(tree,ast.Call):value=mathop(functions[tree.func.id],*(expression(a) for a in tree.args))
            elif isinstance(tree,ast.Compare):
                op={ast.Lt:'LESS_THAN',ast.Gt:'GREATER_THAN'}[type(tree.ops[0])]
                value=mathop(op,expression(tree.left),expression(tree.comparators[0]))
            elif isinstance(tree,ast.IfExp):
                n=node('GeometryNodeSwitch');n.input_type='FLOAT'
                link(expression(tree.test),n.inputs['Switch'])
                attach(expression(tree.body),n.inputs['True']);attach(expression(tree.orelse),n.inputs['False'])
                value=n.outputs['Output']
            else:raise ValueError('Unsupported body graph expression: '+key)
            cache[key]=value;return value
        opcode=named('opcode','INT');result=0.0
        for code,tree in signatures.values():
            if code not in codes:continue
            n=node('GeometryNodeSwitch');n.input_type='FLOAT'
            link(mathop('COMPARE',opcode,code,.1),n.inputs['Switch'])
            attach(expression(tree),n.inputs['True']);attach(result,n.inputs['False']);result=n.outputs[0]
        combine=node('ShaderNodeCombineXYZ');link(mathop('MULTIPLY',result,SCALE),combine.inputs['X'])
        setpos=node('GeometryNodeSetPosition');link(inlet.outputs['Geometry'],setpos.inputs['Geometry'])
        link(combine.outputs[0],setpos.inputs['Position']);link(setpos.outputs[0],outlet.inputs['Geometry'])
        vms[codes]=vm
        return vm
    group=bpy.data.node_groups.new(prefix+'_BODY_EVALUATION','GeometryNodeTree');group['mm_body_helper']=True
    group.interface.new_socket(name='Geometry',in_out='INPUT',socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
    node,link=group.nodes.new,group.links.new
    def geometry(obj):
        n=node('GeometryNodeObjectInfo');n.inputs['Object'].default_value=obj
        n.transform_space='ORIGINAL';return n.outputs['Geometry']
    previous=geometry(source)
    for level,indices in batches.items():
        data=mesh(f'BODY_STAGE_{level}',len(indices))
        attr(data,'opcode','INT',[records[i][0] for i in indices])
        for slot in range(max_inputs):attr(data,'n'+str(slot),'INT',[lookup[records[i][1][slot]] if slot<len(records[i][1]) else 0 for i in indices])
        for slot in range(max(len(records[i][2]) for i in indices)):
            attr(data,'k'+str(slot),'FLOAT',[records[i][2][slot] if slot<len(records[i][2]) else 0.0 for i in indices])
        stage=node('GeometryNodeGroup');stage.node_tree=vm_for({records[i][0] for i in indices});stage.label=f'Body dependency level {level}'
        link(previous,stage.inputs['Previous']);link(geometry(data),stage.inputs['Geometry'])
        join=node('GeometryNodeJoinGeometry');link(stage.outputs[0],join.inputs['Geometry']);link(previous,join.inputs['Geometry'])
        previous=join.outputs[0]
    end=node('NodeGroupOutput');link(previous,end.inputs['Geometry'])
    output=mesh('BODY_OUTPUT',0)
    output.modifiers.new('Native Body Correctives','NODES').node_group=group
    return output,lookup,owned
