# Direct MetaHuman Animator capture

1. On the iPhone, open Live Link Face. Select **MetaHuman Animator** and enable
   **Realtime Animation**. Keep the app in the foreground on the same local network.
2. In MetaMorphosis > Live Link, select the **Face Board / Rig**.
3. Set **Capture Mode** to **MetaHuman Animator** and enter the iPhone's Wi-Fi
   address. The **Phone Control Port** defaults to 14785. **Listen Address** and
   **Port** specify the local UDP listener; the addon negotiates this port with
   the phone. Leave Subject blank unless choosing a particular advertised subject.
4. Normally the head DNA is found from the imported rig. If merging removed its
   metadata, set **MHA Head DNA** to the original matching head DNA file.
5. Click **Connect Live Link**. Start Recording uses the existing three-second
   countdown and creates a separate action. Disconnect closes the phone session.

The phone provides solved MHA facial controls. The bundled native DNA library maps
these controls onto the character's face board. Unreal Engine is not required at
runtime, and the stream is not converted into ARKit coefficients. ARKit-specific
strength, mirroring and inferred mouth settings are hidden in MHA mode. Smoothing
remains available, with a 15 ms maximum for mouth/jaw channels.

This workflow maps raw values to GUI controls; combinations that cannot be
represented by the GUI are not guaranteed to reproduce a direct raw-control solve.
Head motion is not applied. Existing Lite deformation limits still apply. No
objective lip-sync accuracy improvement is claimed yet.

Tested on Live Link Face 1.7.3 (185): 251 controls, 582 received frames, zero invalid
packets and zero queue drops. The recorded sequence mapped to Logan, baked to an
action, and passed standalone save/reopen playback in Blender 5.2. ARKit regression
checks also passed. These checks do not establish support for every app/DNA version.
