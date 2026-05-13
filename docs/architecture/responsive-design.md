# Responsive Design

Round 6b implements the Adiona widget catalogue for desktop-first travel
planning. The primary target is a 1280px+ viewport with the three-column shell:
navigation, chat thread, and contextual right pane.

The widgets use MUI layout primitives and wrap where practical, but mobile
variants are deliberately deferred. The Figma source includes mobile map/filter
concepts (`mob-*` frames); those should be implemented in a separate mobile
round so this desktop pass stays focused and testable.

Current behaviour:

- Cards, lists, and forms constrain text and wrap chips/actions.
- Place grids collapse through MUI breakpoints.
- `MapView` keeps a fixed desktop height and shows a no-key preview fallback.
- The app shell itself remains desktop-oriented.

Deferred mobile work:

- Single-column chat-first shell.
- Drawer-based filters/property block.
- Map/list toggle for hotel search.
- Touch-optimized date and party pickers.
