# Material Widgets 6b

Status: GREEN for repository implementation and static validation.

Round 6b replaced the 23 widget JSON stubs with Material UI v6 components,
added the Adiona-derived theme, loaded Inter locally, and wired
`WidgetRenderer.onWidgetEvent` for interactive widgets. `MapView` uses
`@vis.gl/react-google-maps` when `VITE_GOOGLE_MAPS_KEY` is provided and
degrades to a coordinate preview when it is absent.

Validation covered type generation, TypeScript, widget schema smoke, and Vite
production build. Container validation depends on the local Podman API being
available.
