# Image Testing Rules
- Accepted MIME types: image/jpeg, image/png, image/webp only
- Extract frame 1 from animated images (GIF/APNG/animated WEBP)
- Resize before base64 encode
- Don't send blank or solid-colour images
- Never log full base64 strings — first 10 chars only
