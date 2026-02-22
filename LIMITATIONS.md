## Technical Limitations

- Non-APL devices requires a proxied, internet-accessible HTTPS endpoint for the Music Assistant stream
 
  [This means your Music Assistant stream will be publicly accessible on the internet. Take appropriate security measures to protect your Music Assistant instance.]

- Not currently compatible with Alexa+ on Developer Console Simulator

## Known Issues

### All devices: 
- Skill session does not persist on AlexaPy device commands
- Alexa groups (including stereo) are not supported at this time

### APL devices:
 - If follow up mode is enabled on the device in the Alexa app, the follow up prompt will continously stay open because of the constant metadata refresh
