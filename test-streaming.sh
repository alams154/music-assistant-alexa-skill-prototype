#!/bin/bash
# Diagnostic script to test Music Assistant streaming for Alexa devices

echo "=================================================="
echo "Music Assistant Alexa Streaming Diagnostic Tool"
echo "=================================================="
echo ""

# Get the latest stream URL from the bridge
echo "1. Fetching latest stream URL from bridge..."
STREAM_URL=$(curl -s http://localhost:5000/ma/latest-url | grep -o '"streamUrl":"[^"]*"' | cut -d'"' -f4)

if [ -z "$STREAM_URL" ]; then
    echo "❌ ERROR: No stream URL available. Push a URL from Music Assistant first."
    exit 1
fi

echo "   Stream URL: $STREAM_URL"
echo ""

# Extract the flow path for testing
FLOW_PATH=$(echo "$STREAM_URL" | sed 's|http://[^/]*/|/|')
PUBLIC_URL="https://music-assistant.jayekub.com${FLOW_PATH}"

echo "2. Testing public URL accessibility..."
echo "   Testing: $PUBLIC_URL"
echo ""

# Test basic connectivity
echo "   a) Basic HEAD request:"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -I "$PUBLIC_URL" 2>&1)
if [ "$HTTP_CODE" = "200" ]; then
    echo "      ✅ HEAD request: $HTTP_CODE OK"
else
    echo "      ❌ HEAD request failed: $HTTP_CODE"
fi
echo ""

# Test Range request support (CRITICAL for Alexa)
echo "   b) Range request test (CRITICAL FOR ALEXA):"
RANGE_RESPONSE=$(curl -s -I -H "Range: bytes=0-1023" "$PUBLIC_URL" 2>&1)
RANGE_CODE=$(echo "$RANGE_RESPONSE" | grep -oP "HTTP/[0-9.]+ \K[0-9]+")
ACCEPT_RANGES=$(echo "$RANGE_RESPONSE" | grep -i "Accept-Ranges:" | cut -d: -f2 | tr -d ' \r')

if [ "$RANGE_CODE" = "206" ]; then
    echo "      ✅ Range requests supported! (HTTP 206 Partial Content)"
elif [ "$RANGE_CODE" = "200" ]; then
    echo "      ❌ Range requests NOT supported! (HTTP 200 instead of 206)"
    echo "      ⚠️  This is likely why Alexa devices can't play audio!"
else
    echo "      ❌ Range request failed: HTTP $RANGE_CODE"
fi

if [ -n "$ACCEPT_RANGES" ]; then
    echo "      Accept-Ranges header: $ACCEPT_RANGES"
else
    echo "      ⚠️  No Accept-Ranges header found"
fi
echo ""

# Test content type
echo "   c) Content-Type check:"
CONTENT_TYPE=$(curl -s -I "$PUBLIC_URL" | grep -i "Content-Type:" | cut -d: -f2 | tr -d ' \r')
echo "      Content-Type: $CONTENT_TYPE"
if [[ "$CONTENT_TYPE" =~ ^audio/ ]]; then
    echo "      ✅ Valid audio content type"
else
    echo "      ⚠️  Unexpected content type (expected audio/*)"
fi
echo ""

# Test Music Assistant directly
echo "3. Testing Music Assistant endpoint directly..."
MA_URL="http://192.168.0.5:8098${FLOW_PATH}"
echo "   Testing: $MA_URL"

MA_RANGE=$(curl -s -I -H "Range: bytes=0-1023" "$MA_URL" 2>&1 | grep -oP "HTTP/[0-9.]+ \K[0-9]+")
if [ "$MA_RANGE" = "206" ]; then
    echo "   ✅ Music Assistant supports Range requests (HTTP 206)"
elif [ "$MA_RANGE" = "200" ]; then
    echo "   ❌ Music Assistant does NOT support Range requests"
    echo "   ⚠️  Music Assistant itself needs Range request support for Alexa"
else
    echo "   ❌ Test failed: HTTP $MA_RANGE"
fi
echo ""

# Summary
echo "=================================================="
echo "SUMMARY & DIAGNOSIS"
echo "=================================================="
echo ""

if [ "$RANGE_CODE" = "206" ]; then
    echo "✅ Your setup appears to support Range requests correctly!"
    echo ""
    echo "If Alexa still fails, the issue is likely:"
    echo "  1. Public accessibility from Amazon's cloud (not your network)"
    echo "  2. SSL certificate validation (even if Let's Encrypt, check CN)"
    echo "  3. Audio codec compatibility (Samsung might not support the format)"
    echo "  4. Flow tokens expiring too quickly"
    echo ""
    echo "Next steps:"
    echo "  - Test from outside your network (phone with WiFi OFF)"
    echo "  - Check Nginx access logs during Alexa playback attempt"
    echo "  - Verify audio codec with: ffprobe <stream-url>"
else
    echo "❌ RANGE REQUEST SUPPORT IS MISSING!"
    echo ""
    echo "Alexa devices REQUIRE HTTP Range request support for audio streaming."
    echo ""
    if [ "$MA_RANGE" != "206" ]; then
        echo "Issue: Music Assistant doesn't support Range requests"
        echo ""
        echo "You need to configure Music Assistant to support Range requests."
        echo "Check Music Assistant settings or update to a version that supports it."
    else
        echo "Issue: Nginx is not forwarding Range requests correctly"
        echo ""
        echo "Fix: Add these lines to your Nginx proxy configuration:"
        echo ""
        echo "  proxy_set_header Range \$http_range;"
        echo "  proxy_set_header If-Range \$http_if_range;"
        echo "  proxy_http_version 1.1;"
        echo "  proxy_set_header Connection \"\";"
    fi
fi

echo ""
echo "Run this test again after making changes to verify the fix."
echo "=================================================="
