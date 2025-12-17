## Supported Regions & Languages

- **Prototype support:** en-US only.

## Supported Devices (tested)

- **Echo (Gen 1)**
- **Echo Show 8 (Gen 2)** — supports APL

## Technical Limitations

- Non-APL devices require proxied, internet-accessible HTTPS endpoints for media streaming.

## Known Issues

- APL devices: pause and stop intents are not handled reliably.
- All devices: there is a noticeable delay when pausing; this is caused by the AlexaPy library.
- APL devices: album art is not currently displayed.

If you want, I can open a small follow-up PR to add troubleshooting steps or suggested workarounds for these issues.
