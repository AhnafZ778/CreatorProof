# Artist artwork registration

Updated on 2026-10-09. The registration panel now fills the Artist workspace
instead of leaving a large empty column. Its dark surfaces, restrained violet
accent, rounded controls and typography match the rest of the portal.

Desktop places the reference image and artwork details side by side. On smaller
screens they stack. The upload canvas supports browsing and native file drops,
shows the complete image without cropping, and displays its name and size.
Artists can replace or remove an image while retaining their entered details.
Object URLs are released when the image changes or the component unmounts.

The enrollment-screening explanation is a compact disclosure below the fields.
Advanced catalog and claim settings remain available in their own disclosure.
The submit button has its own size rather than inheriting the shared full-width
button rule inside a horizontal footer. Pending registration disables edits
and shows a progress indicator; failures preserve the selected file and fields.

The existing upload limits, screening policy, API payload, refusal handling,
successful registration and library navigation are preserved.

Verification covered layout at 390/640/1024/1440px without horizontal overflow,
image loading, replacement/removal, actual native drag-and-drop, disclosure
controls, submitted fields/file bytes, pending/error recovery and tab navigation.
Submission checks intercepted the request in an isolated browser context; they
did not enroll extra artwork or run external inference. All six browser check
groups passed with zero page errors. TypeScript, frontend tests and the
production build passed.

Captures: [empty form](assets/artist-registration/desktop-empty.png),
[image preview](assets/artist-registration/desktop-preview.png),
[mobile](assets/artist-registration/mobile-empty.png), and
[verification](assets/artist-registration/verification.json).
