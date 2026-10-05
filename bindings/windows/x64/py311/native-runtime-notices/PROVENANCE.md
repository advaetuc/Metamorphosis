# Blender Integration Math

The transform and eye-chain compatibility implementations in `src/Transform.cpp`
and `src/Frame.cpp` follow the
numerical conventions of Blender's math utilities and pose-channel application.
Reference files in Blender are `math_rotation_c.cc`, `math_matrix_c.cc` and
`armature.cc` (GPL-2.0-or-later). This integration-specific compatibility code must
be distributed consistently with those GPL obligations; it is not a change to,
or relicensing of, the MIT OpenRigLogic SDK. Keep it within the optional Blender
integration module. No Blender-private functions or structures are linked.
