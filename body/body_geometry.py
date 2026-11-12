"""Landmark fitted custom body controls; evaluated only during conversion."""
import math
from mathutils import Vector


def align_z(bone, direction):
    y = (bone.tail - bone.head).normalized()
    z = Vector(direction) - y * Vector(direction).dot(y)
    if z.length > 1e-8:
        bone.align_roll(z.normalized())


def pole_angle(bones, upper, lower, pole):
    b = bones[upper]
    axis = (bones[lower].tail_local - b.head_local).normalized()
    v = bones[pole].head_local - b.head_local
    v = (v - axis * v.dot(axis)).normalized()
    x = b.matrix_local.to_3x3().col[0]
    x = (x - axis * x.dot(axis)).normalized()
    return -math.atan2(axis.dot(x.cross(v)), x.dot(v))


def fit(rig, source, mesh_points):
    """Fit the bundled 454-bone topology without touching any DNA bone."""
    b = rig.data.edit_bones
    for side in 'LR':
        b['DEF_COR_THIGH_INN..'+side].parent=b['ORG_THIGH.'+side]
    p = {n: m.translation.copy() for n, m in source.items()}
    ground = min(v.z for v in mesh_points)
    H = p['head'].z - ground
    if H <= 0:
        raise ValueError('The body must be upright in armature space')
    s = H / 1.5466
    old = {n: (v.head.copy(), v.tail.copy(), v.roll) for n, v in b.items()}
    # Initial proportional placement covers display stubs. Every functional
    # chain and muscle is assigned anatomical landmarks below.
    old_h = old['HEAD'][0].z
    for bone in b:
        bone.head *= H / old_h
        bone.tail *= H / old_h

    def put(name, head, tail, z=None, roll=0):
        if name not in b:
            return
        bone = b[name]
        bone.use_connect = False
        bone.head, bone.tail = head, tail
        if (bone.tail-bone.head).length < H*1e-7:
            bone.tail = bone.head + Vector((0, H*.01, 0))
        bone.roll = roll
        if z is not None:
            align_z(bone, z)

    def copy(name, other, fraction=1):
        v = b[other]
        put(name, v.head.copy(), v.head.lerp(v.tail, fraction), roll=v.roll)

    def stub(name, head, delta):
        put(name, head, Vector(head)+Vector(delta)*s)

    hips0 = Vector((0, 0, p['thigh_l'].z*.82))
    hips1 = p['spine_02']; spine1 = p['spine_03']; chest0 = p['spine_04']
    chest1 = p['neck_01']; head0 = p['head']
    head1 = head0 + Vector((0, 0, 2.7*(head0-chest1).length))
    segments = {'HIPS':(hips0, hips1), 'SPINE_01':(hips1, spine1),
                'SPINE_02':(spine1, chest0), 'CHEST':(chest0,chest1),
                'NECK':(chest1,head0),'HEAD':(head0,head1)}
    for name, (a,c) in segments.items():
        for prefix in ('ORG_', 'DEF_'):
            put(prefix+name,a,c,(0,-1,0))
        put(name+'_TWEAK',a,a+(c-a).normalized()*H*.04,(0,-1,0))
    put('HEAD_TIP_TWEAK',head1,head1+Vector((0,0,H*.04)),(0,-1,0))
    for name in ('NECK',):
        put(name,*segments[name],(0,-1,0))
    # Final HEAD control sits at the face-rig skull/neck junction rather than
    # the lower native head joint, while ORG_HEAD/HEAD_TWEAK keep DNA rest poses.
    nh_len = (head0 - chest1).length
    head_ctrl_0 = Vector((head0.x, chest1.y - 0.3080 * nh_len, chest1.z + 0.5985 * nh_len))
    head_ctrl_1 = head_ctrl_0 + Vector((0, 0, 1.8630 * nh_len))
    put('HEAD', head_ctrl_0, head_ctrl_1, (0, -1, 0))
    for name, length in (('ROOT',.32),('ROOT_02',.47)):
        put(name,(0,0,ground),(0,H*length,ground))
    stub('PROPERTIES',head1+Vector((0,0,H*.11)),(0,0,.09*1.5466))
    for name,length in (('TORSO',.12),('CHEST',.09),('HIPS',.065)):
        a=spine1-Vector((0,0,.02*H)) if name=='TORSO' else spine1
        put(name,a,a+Vector((0,length*H,0)))
    put('HIPS_FK',hips1,hips1.lerp(chest0,1.3),(0,-1,0))
    put('SPINE_01_FK',spine1,spine1.lerp(chest0,.85),(0,-1,0))
    put('SPINE_02_FK',spine1,spine1.lerp(chest0,.9),(0,-1,0))
    put('CHEST_FK',chest0,chest1,(0,-1,0))
    for name,a,delta in (
        ('MCH_SPINE_01_FK',spine1,(0,.024,0)),('MCH_SPINE_02_FK',spine1,(0,.035,0)),
        ('VIS_CHEST',spine1,(0,.031,0)),('VIS_HIPS',spine1,(0,.021,0)),
        ('MCH_HIPS_FK',hips1,(0,.038,0)),('MCH_CHEST_FK',chest0,(0,.058,0)),
        ('MCH_PIVOT',spine1,(0,-.0014,.0235)),('MCH_NECK',chest1,(0,.047,0)),
        ('MCH_INT_NECK',chest1,(0,.032,0)),('MCH_HEAD',head0,(0,.037,0)),
        ('MCH_INT_HEAD',head0,(0,.024,0))):stub(name,a,delta)

    for side, suffix in (('L','l'),('R','r')):
        sign = 1 if side=='L' else -1
        S='.'+side
        def pp(n):return p[n+'_'+suffix]
        def cp(n,o,f=1):copy(n+S,o+S,f)
        def st(n,a,d):stub(n+S,a,d)
        def pt(n,a,c,z=None,roll=0):put(n+S,a,c,z,roll)
        def hinge(a,c,d,fallback):
            z=(c-a).cross(d-c)
            if z.length < 1e-5:z=Vector(fallback)
            if z.dot(Vector(fallback)) < 0:z.negate()
            return z.normalized()
        arm0,arm1,arm2=pp('upperarm'),pp('lowerarm'),pp('hand')
        leg0,leg1,leg2=pp('thigh'),pp('calf'),pp('foot')
        na=hinge(arm0,arm1,arm2,(-.8*sign,0,-.6))
        nl=hinge(leg0,leg1,leg2,(sign,0,0))
        pt('SHOULDER',pp('clavicle'),arm0,(0,0,1));cp('DEF_SHOULDER','SHOULDER')
        handtail=arm2+(arm2-arm1)*.25
        foot_points=[v for v in mesh_points if v.x*sign>0 and v.z<leg2.z*.9]
        if not foot_points:raise ValueError('Cannot identify the foot surface')
        back=max(v.y for v in foot_points);tip=min(v.y for v in foot_points)
        inner=min(v.x*sign for v in foot_points)*sign
        outer=max(v.x*sign for v in foot_points)*sign
        mid=(back+tip)/2;fl=back-tip;ball=pp('ball')
        toetip=Vector((ball.x,tip+.025*s,ball.z))
        chain={'ARM':(arm0,arm1,na),'FOREARM':(arm1,arm2,na),'HAND':(arm2,handtail,na),
               'THIGH':(leg0,leg1,nl),'SHIN':(leg1,leg2,nl),
               'FOOT':(leg2,ball,(sign,0,0)),'TOE':(ball,toetip,(0,0,1))}
        tweak_sizes={'ARM':.04,'FOREARM':.04,'HAND':.04,'THIGH':.10,'SHIN':.08,'FOOT':.08,'TOE':.08}
        for name,(a,c,z) in chain.items():
            for prefix in ('ORG_','DEF_','MCH_IK_','MCH_SWITCH_'):
                pt(prefix+name,a,c,z)
            pt(name+'_FK' if name!='TOE' else name,a,c,z)
            pt(name+'_TWEAK',a,a+(c-a).normalized()*tweak_sizes[name]*s,z)
        cp('HAND_IK','HAND_FK')
        cp('HAND_SEC_TWEAK','HAND_TWEAK')
        pt('HAND_TIP_TWEAK',handtail,handtail+(arm2-arm1).normalized()*.025*s,na)
        cp('SHIN_TWEAK_01','SHIN_TWEAK')
        pt('TOE_TIP_TWEAK',toetip,toetip+Vector((0,-.08*s,0)),(0,0,1))
        for name,count in (('ARM',4),('FOREARM',4),('THIGH',2)):
            a,c,z=chain[name]
            for i in range(1,count+1):
                h=a.lerp(c,(i-1)/count);t=a.lerp(c,i/count)
                for prefix in ('ORG_','DEF_'):pt(prefix+name+f'_{i:02}',h,t,z)
                pt(name+f'_{i:02}_TWEAK',h,h+(c-a).normalized()*.025*s,z)
        for limb,a,c,d,factor,fallback in (('ARM',arm0,arm1,arm2,.77,(0,1,0)),('LEG',leg0,leg1,leg2,.5,(0,-1,0))):
            chord=d-a;off=c-(a+chord*(c-a).dot(chord)/chord.length_squared)
            if off.length<1e-5:off=Vector(fallback)
            pole=c+off.normalized()*factor*((c-a).length+(d-c).length)
            st(limb+'_IK_POLE',pole,(0,.055 if limb=='ARM' else .08,0))
            pt('VIS_'+limb+'_IK_POLE',c,pole,(0,0,1))
            st('MCH_FK_IK_'+limb+'_IK_POLE',pole,(0,.029 if limb=='ARM' else .042,0))
        for name,a,delta in (
            ('MCH_ARM_SOCKET',arm0,(0,0,.045)),('MCH_INT_ARM_SOCKET',arm0,(0,0,.027)),
            ('MCH_HAND_IK',arm2,(0,0,.033)),('MCH_ARM_IK_POLE',b['ARM_IK_POLE'+S].head,(0,.032,0)),
            ('MCH_THIGH_SOCKET',leg0,(0,0,.065)),('MCH_INT_THIGH_SOCKET',leg0,(0,0,.038)),
            ('MCH_PARENTS_LEG_IK_POLE',b['LEG_IK_POLE'+S].head,(0,.041,0))):st(name,a,delta)
        cp('MCH_TWIST_ARM','ARM_FK',.233);cp('MCH_FOREARM_TWEAK','FOREARM_FK',.11)
        cp('MCH_THIGH_TWIST','THIGH_FK',.359);cp('MCH_SHIN_TWEAK','SHIN_FK',.144);cp('MCH_TOE','TOE',.57)
        pt('FOOT_IK',(ball.x,leg2.y-.25*fl,ground),(ball.x,back+.03*fl,ground))
        st('MCH_PARENTS_FOOT_IK',b['FOOT_IK'+S].head,(0,.058,0))
        pt('HEEL',(ball.x,back+.07*fl,leg2.z*.92),(ball.x,back+.07*fl,leg2.z*.92+.05*s),(0,-1,0))
        pt('MCH_FOOT_ROLL_EXTEND',(ball.x,tip,ground),(ball.x,back,ground))
        pt('MCH_FOOT_SIDE_ROLL_01',(inner,mid,ground),(outer,mid,ground),(0,-1,0))
        pt('MCH_FOOT_SIDE_ROLL_02',(outer,mid,ground),(inner,mid,ground),(0,-1,0))
        pt('MCH_FOOT_ROLL_02',(ball.x,back,ground),(ball.x,back,ground+.065*s),(0,-1,0))
        pt('MCH_FOOT_ROLL_01',ball,(ball.x,back,ground),(0,1,0))
        for digit,letter in (('thumb',None),('index','A'),('middle','B'),('ring','C'),('pinky','D')):
            sources=([digit+'_metacarpal'] if letter else [])+[digit+f'_{i:02}' for i in (1,2,3)]
            for i,n in enumerate(sources):
                a=pp(n);c=pp(sources[i+1]) if i+1<len(sources) else a+(a-pp(sources[i-1]))*.85
                name=('FINGER_'+letter if letter else 'THUMB')+f'_{i+1:02}'
                z=source[n+'_'+suffix].to_3x3().col[2]
                pt(name,a,c,z);cp('DEF_'+name,name)
        cp('MCH_FINGER_B_01','FINGER_B_01',.75);cp('MCH_FINGER_C_01','FINGER_C_01',.75)
        cp('HAND_SIDE_OPEN','FINGER_D_01',.8)
        # Muscle locations are normalized by the actual local limb lengths.
        av=arm1-arm0;al=av.length;ua=av.normalized();uf=(arm2-arm1).normalized()
        tv=leg1-leg0;tl=tv.length;ut=tv.normalized()
        def vec(v):return Vector((v[0]*sign,v[1],v[2]))
        for name,f,offset,length in (
            ('COR_BBONE_01_BICEP',.169,(-.080,-.204,-.015),.147),
            ('COR_BBONE_02_BICEP',.894,(-.056,-.140,-.011),.147),
            ('COR_BBONE_02_TRICEP',.830,(.025,.197,-.026),.147)):
            a=arm0+av*f+vec(offset)*al;pt(name,a,a+ua*length*al,na)
        pt('COR_BBONE_01_TRICEP',arm0+av*.046+vec((.042,.308,-.038))*al,arm0+av*.172+vec((.037,.268,-.033))*al,na)
        for kind in ('BICEP','TRICEP'):
            for i in (1,2):
                n=f'COR_BBONE_{i:02}_{kind}';cp('ORG_'+n,n,.75);cp('DEF_'+n,'ORG_'+n if 'ORG_'+n+S in b else n)
            a=b[('ORG_' if kind=='BICEP' else '')+'COR_BBONE_01_'+kind+S].tail
            c=b['ORG_COR_BBONE_02_'+kind+S].head
            for prefix in ('ORG_','DEF_'):pt(prefix+'COR_'+kind,a,c,na)
        bis=ua-uf
        if bis.length<1e-5:bis=Vector((0,1,0))
        bis.normalize()
        for name,f in (('ELBOW',.185),('INNER_FORRARM',-.174)):
            for prefix in ('ORG_','DEF_'):pt(prefix+'COR_'+name,arm1,arm1+bis*f*al,na)
        for name,f,off,delta in (
            ('FRONT_01',.218,(.019,-.204,.006),(ut*.998+Vector((0,.044,0))).normalized()*.081),
            ('FRONT_02',.938,(.004,-.156,.004),(ut*.998+Vector((0,.044,0))).normalized()*.075),
            ('BACK_01',.238,(.040,.230,-.003),Vector((0,-.010,-.082))),
            ('BACK_02',.910,(-.017,.166,-.005),Vector((0,-.011,-.090)))):
            a=leg0+tv*f+vec(off)*tl;pt('COR_THIGH_'+name,a,a+delta*tl,nl)
        for kind in ('FRONT','BACK'):
            for prefix in ('ORG_','DEF_'):pt(prefix+'COR_THIGH_'+kind,b['COR_THIGH_'+kind+'_01'+S].tail,b['COR_THIGH_'+kind+'_02'+S].head,nl)
        for name,a,delta,z in (
            ('THIGH_INN',leg0+tv*.712+vec((-.150,-.061,-.007))*tl,Vector((0,.105,0)),None),
            ('THIGH_OUT',leg0+tv*.579+vec((.200,-.028,.013))*tl,Vector((0,.105,0)),None),
            ('KNEE',leg1,vec((.005,-.147,-.024)),nl),('THIGH_INN.',leg1,vec((.006,.184,.030)),-nl),
            ('FOOT_UPPER',leg2,vec((.015,-.139,.093)),nl)):
            for prefix in ('ORG_','DEF_'):pt(prefix+'COR_'+name,a,a+delta*tl,z)
        sw=abs(arm0.x);ch=chest1.z-chest0.z
        for name,h,t,roll in (
            ('CHEST_UPPER',(-.121,-.681,.575),(.017,-.683,.608),-107.30),
            ('CHEST_MID',(-.103,-.757,.318),(.012,-.779,.375),-126.89),
            ('CHEST_LOWER',(.095,-.816,.177),(.199,-.820,.244),-126.72),
            ('UNDERARM',(.755,-.233,-.273),(.799,-.207,-.175),-145.86),
            ('BACK_LOWER',(.389,.308,-.370),(.456,.339,-.278),-167.47),
            ('BACK_MID',(.153,.521,-.046),(.245,.525,.033),-150.96),
            ('BACK_UPPER',(-.113,.548,.316),(.023,.596,.334),-130.58),
            ('TRAPEZIUM',(.244,-.038,1.219),(.358,.018,1.180),-115.18)):
            cv=lambda v:Vector((v[0]*sw*sign,v[1]*sw,chest0.z+v[2]*ch))
            pt('COR_'+name,cv(h),cv(t),roll=math.radians(roll)*sign)
            end=arm0  # Stretch To targets the shoulder tail, including UNDERARM.
            for prefix in ('ORG_','DEF_'):pt(prefix+'COR_'+name,cv(t),end,(0,1,0))
    return H
