"""Scalar body-corrective graph; all emitted expressions use Blender's native subset."""
import math
import numpy as np


class Graph:
    SCALE = 10000.0

    def __init__(self):
        self.nodes = []
        self.cache = {}

    def emit(self, expression, *inputs):
        key=(expression,inputs)
        if key in self.cache:
            return self.cache[key]
        index = len(self.nodes)
        self.nodes.append((expression, inputs))
        self.cache[key]=index
        return index

    def constant(self, value):
        return self.emit(format(float(value), '.12g'))

    def weighted(self, nodes, weights):
        terms = [(n, w) for n, w in zip(nodes, weights) if w != 0]
        if not terms:
            return self.constant(0)
        partial = []
        for start in range(0, len(terms), 4):
            group = terms[start:start+4]
            expression = '+'.join(f'{float(w):.9g}*{chr(97+i)}' for i, (_, w) in enumerate(group))
            partial.append(self.emit(expression, *(n for n, _ in group)))
        return partial[0] if len(partial) == 1 else self.weighted(partial, [1]*len(partial))

    def multiply(self, nodes):
        value = self.constant(1)
        for node in nodes:
            value = self.emit('a*b', value, node)
        return value

    def project(self, quaternion, method, axis):
        if method not in (2, 3):
            return quaternion
        a, w = quaternion[axis], quaternion[3]
        length = self.emit('sqrt(a*a+b*b)', a, w)
        result = [self.constant(0) for _ in range(4)]
        if method == 3:
            result[axis] = self.emit('a/max(b,1e-10)', a, length)
            result[3] = self.emit('a/max(b,1e-10)', w, length)
        else:
            b, c = (axis+1)%3, (axis+2)%3
            numerator = self.emit('a*b-c*d', w, quaternion[b], a, quaternion[c])
            result[b] = self.emit('-a/max(b,1e-10)', numerator, length)
            numerator = self.emit('a*b+c*d', w, quaternion[c], a, quaternion[b])
            result[c] = self.emit('-a/max(b,1e-10)', numerator, length)
            result[3] = self.emit('-a', length)
        return result

    def quaternion_product(self, a, b):
        return [self.emit(expr,*(a+b)) for expr in
                ('d*e+a*h+b*g-c*f','d*f-a*g+b*h+c*e',
                 'd*g+a*f-b*e+c*h','d*h-a*e-b*f-c*g')]

    def compile_rotations(self, reader, controls, lod):
        """Quaternion-authored joint groups use ordered normalized lerps, not Euler sums."""
        from mathutils import Euler
        result={}
        for group in range(reader.getJointGroupCount()):
            inputs=list(reader.getJointGroupInputIndices(group))
            outputs=list(reader.getJointGroupOutputIndices(group))
            values=np.asarray(reader.getJointGroupValues(group)).reshape(len(outputs),len(inputs))
            count=list(reader.getJointGroupLODs(group))[lod]
            rows={out:values[i] for i,out in enumerate(outputs[:count])}
            joints={out//9 for out in rows if out%9 in (3,4,5)}
            for joint in sorted(joints):
                if int(reader.getJointRotationRepresentation(joint))!=1:continue
                angles=np.asarray([rows.get(joint*9+a,np.zeros(len(inputs))) for a in (3,4,5)]).T
                accumulator=None
                for control,euler in zip(inputs,angles):
                    if not np.any(euler):continue
                    q=Euler(tuple(np.radians(euler)),'XYZ').to_quaternion()
                    # Choose the same hemisphere as identity before blending.
                    if q.w<0:q.negate()
                    weight=controls[control]
                    norm=self.emit(f'1/sqrt(max(1e-20,1+{2*(q.w-1):.12g}*a*(1-a)))',weight)
                    t=self.emit('a*b',weight,norm)
                    part=[self.emit(f'{v:.12g}*a',t) for v in (q.x,q.y,q.z)]
                    part.append(self.emit(f'(1+{q.w-1:.12g}*a)*b',weight,norm))
                    accumulator=part if accumulator is None else self.quaternion_product(part,accumulator)
                if accumulator is not None:result[joint]=accumulator
        return result

    def inverse_quaternion(self, q):
        return [self.emit('-a',v) for v in q[:3]]+[q[3]]

    def slerp_identity(self,q,weight):
        sign=self.emit('-1 if a<0 else 1',q[3])
        q=[self.emit('a*b',v,sign) for v in q]
        angle=self.emit('acos(min(1,max(-1,a)))',q[3])
        factor=self.emit(f'sin({1-weight:.12g}*a)/sin(a) if a>1e-6 else {1-weight:.12g}',angle)
        return [self.emit('a*b',v,factor) for v in q[:3]]+[self.emit(f'cos({1-weight:.12g}*a)',angle)]

    def compile_twist_swing(self, reader, raw):
        result={}
        swings={tuple(reader.getSwingInputControlIndices(i)):i for i in range(reader.getSwingCount())}
        for index in range(reader.getSwingCount()):
            inputs=list(reader.getSwingInputControlIndices(index))
            axis=int(reader.getSwingSetupTwistAxis(index))
            q=[raw[i] for i in inputs]
            twist=self.project(q,3,axis)
            invtwist=self.inverse_quaternion(twist)
            invswing=self.inverse_quaternion(self.quaternion_product(q,invtwist))
            for joint,weight in zip(reader.getSwingOutputJointIndices(index),reader.getSwingBlendWeights(index)):
                result[joint]=self.quaternion_product(invtwist,self.slerp_identity(invswing,float(weight)))
        for index in range(reader.getTwistCount()):
            inputs=tuple(reader.getTwistInputControlIndices(index))
            axis=int(reader.getTwistSetupTwistAxis(index))
            twist=self.project([raw[i] for i in inputs],3,axis)
            if inputs in swings:
                twist=self.inverse_quaternion(twist)
            for joint,weight in zip(reader.getTwistOutputJointIndices(index),reader.getTwistBlendWeights(index)):
                result[joint]=self.slerp_identity(twist,float(weight))
        return result

    def compile_rbf(self, model, raw):
        controls = dict(enumerate(raw))
        projections = {}
        for solver in model.solvers:
            if len(solver.inputs) != 4 or solver.method not in (1, 2, 3):
                raise ValueError('Body driver compiler requires single-quaternion RBF inputs')
            key = (tuple(solver.inputs), solver.method, solver.axis)
            if key not in projections:
                projections[key] = self.project([raw[i] for i in solver.inputs], solver.method, solver.axis)
            q = projections[key]
            kernels = []
            for target in solver.targets:
                dot = self.weighted(q, target)
                distance = self.emit('acos(min(1,max(-1,2*a*a-1)))', dot)
                radius = solver.radius
                if solver.function == 0:
                    value = self.emit(f'exp(-a/{radius*radius:.12g})', distance)
                elif solver.function == 1:
                    value = self.emit(f'exp(-2*a/{radius:.12g})', distance)
                else:
                    power = {2:1,3:3,4:5}[solver.function]
                    ratio = self.emit(f'a/{radius:.12g}', distance)
                    powered = ratio if power == 1 else self.emit('*'.join(['a']*power), ratio)
                    value = self.emit('max(0,1-a)', powered)
                kernels.append(value)
            weights = [self.emit('min(1,max(0,a))', self.weighted(kernels, row)) for row in solver.coefficients]
            total = self.weighted(weights, [1]*len(weights))
            divisor = self.emit('max(a,1e-10)' if solver.normalize else 'max(1,a)', total)
            terms = {}
            for pose, weight, scale in zip(solver.poses, weights, solver.scales):
                value = self.emit(f'a/b*{float(scale):.12g}', weight, divisor)
                value = self.emit(f'a if a>{solver.threshold:.12g} else 0', value)
                if model.pose_inputs[pose]:
                    value = self.emit('a*b', value, self.multiply([controls[i] for i in model.pose_inputs[pose]]))
                for out, multiplier in zip(model.pose_outputs[pose], model.pose_weights[pose]):
                    terms.setdefault(out, []).append((value, multiplier))
            for out, items in terms.items():
                controls[out] = self.weighted([v for v,_ in items], [w for _,w in items])
        return controls

    def realize(self, collection, prefix, raw_source, raw_count, raw_names=None, rig=None):
        """Realize scalar helpers driven by a supplied ID's mm_body_raw array.

        Nodes 0..raw_count-1 are raw leaves; all other node inputs refer to earlier
        nodes. Chunking the arrays avoids very large per-ID driver lists.
        """
        import bpy
        levels=[]
        groups={}
        for index,(_,inputs) in enumerate(self.nodes):
            level=1+max((levels[i] for i in inputs),default=-1)
            levels.append(level)
            groups.setdefault(level,[]).append(index)
        holders=[]
        locations={}
        for level,indices in groups.items():
            obj=bpy.data.objects.new(f'{prefix}_BODY_VALUES_{level:02d}',None)
            collection.objects.link(obj)
            obj['mm_body_values']=[0.0]*len(indices)
            for slot,index in enumerate(indices):
                locations[index]=(obj,slot)
            obj['mm_body_helper']=True
            obj.hide_render=True
            obj.hide_set(True)
            holders.append(obj)
        for index,(expression,inputs) in enumerate(self.nodes):
            holder,slot=locations[index]
            f=holder.driver_add('["mm_body_values"]',slot)
            d=f.driver;d.type='SCRIPTED'
            if index<raw_count:
                v=d.variables.new();v.name='raw'
                if raw_names is not None:
                    bone,axis=raw_names[index].rsplit('.',1)
                    v.type='TRANSFORMS';v.targets[0].id=rig
                    v.targets[0].bone_target=bone
                    v.targets[0].transform_type='ROT_'+axis[-1].upper()
                    v.targets[0].rotation_mode='QUATERNION'
                    v.targets[0].transform_space='LOCAL_SPACE'
                else:
                    v.type='SINGLE_PROP'
                    v.targets[0].id=raw_source;v.targets[0].data_path=f'["mm_body_raw"][{index}]'
                d.expression='10000*raw'
            else:
                for i,source in enumerate(inputs):
                    v=d.variables.new();v.name=chr(97+i);v.type='SINGLE_PROP'
                    v.targets[0].id=locations[source][0]
                    v.targets[0].data_path=f'["mm_body_values"][{locations[source][1]}]'
                # Replace symbols with restored units, then scale the output.
                import re
                restored=re.sub(r'\b[a-z]\b',lambda m:f'({m[0]}/10000)',expression)
                d.expression=f'10000*({restored})'
            if len(d.expression.encode())>235:
                raise ValueError('Body expression exceeds native driver size')
        return holders, locations
