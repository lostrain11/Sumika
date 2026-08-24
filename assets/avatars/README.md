# Bundled Avatar assets

`AvatarSample_A.vrm` is the current first-run Sumika demo Avatar. It is a
VRoid Studio sample model distributed in the public
[madjin/vrm-samples](https://github.com/madjin/vrm-samples) repository. Sumika
stores the file as a local registration and loads it only in the local browser
VRM renderer; it is never uploaded or executed as a program.

The former `VRM1_Constraint_Twist_Sample.vrm` is archived outside the active
Avatar directory. Changing the first-run seed does not change an Avatar already
selected in an existing data directory.

## Current default: AvatarSample_A

- Source file: `https://raw.githubusercontent.com/madjin/vrm-samples/e16eb187100149a315ad92c3c9968f1d5baa6c7d/vroid/stable/AvatarSample_A.vrm`
- Repository: `https://github.com/madjin/vrm-samples`
- Pinned commit: `e16eb187100149a315ad92c3c9968f1d5baa6c7d`
- File size: `15,096,320` bytes
- SHA-256: `B86B0B8A66D48911431D6F920A5211A974226F83AA672ECA3F3DFADE58AC346E`
- Embedded author: `VRoid`
- Embedded permissions: everyone, commercial use allowed
- Embedded license label: `Other` (the embedded URL is empty)
- Terms: [VRoid Studio sample model conditions](https://vroid.pixiv.help/hc/en-us/articles/4402394424089)
- Embedded thumbnail: `AvatarSample_A.thumbnail.png`
- Thumbnail size: `2,048 x 2,048` pixels, `1,724,604` bytes
- Thumbnail SHA-256: `FB842AC062564CCB199555C20170DAD502C63D87007D4F602712C194175349D8`

The upstream sample repository README identifies `AvatarSample_A`, `B`, and
`C` as models that may be altered and distributed when their conditions of use
are followed. Review the linked terms before making a separate distribution or
derivative asset.

## Archived reference: VRM1_Constraint_Twist_Sample

The former sample is retained at
`deprecated/20260822T172058Z/assets/avatars/` for recovery, but is not scanned
or offered by the active Avatar catalog.

- Source file: `https://raw.githubusercontent.com/pixiv/three-vrm/cbd9a77a0d17f0099fdac5dcc2b4c7ee30342869/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm`
- Repository: `https://github.com/pixiv/three-vrm`
- Pinned commit: `cbd9a77a0d17f0099fdac5dcc2b4c7ee30342869`
- File size: `10,776,032` bytes
- SHA-256: `12C2B97E95E700783A6A550DC0EEE2D7880AEEDCCEF9AE67BC4C5A2F0F2631A2`
- Embedded author: `pixiv Inc.`
- Embedded thumbnail: `VRM1_Constraint_Twist_Sample.thumbnail.png`
- Thumbnail size: `2,048 x 2,048` pixels, `1,243,889` bytes
- Thumbnail SHA-256: `95B64EC1F832D0E4E0FEE12ED339083E0E8881A3F610798BBBB714A926ED1911`
- Terms: [VRM Public License 1.0](https://vrm.dev/licenses/1.0/)

Both thumbnails are extracted byte-for-byte from their VRM `Thumbnail` image
and served only as local UI previews. They are not independent character
assets. Neither bundled model is an official Sumika character or an endorsement
by its upstream author.

## 相关文档

- [Avatar 资产与驱动](../../docs/architecture/avatar.md)
- [来源与许可证台账](../../docs/ui/license-ledger.md)
- [状态矩阵](../../docs/status-matrix.md)
