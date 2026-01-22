// Extract video URL from response
const output = $input.first().json.body.output;

if (output.status === 'error') {
  return { error: output.error || output.message };
}

// Return video details
return [{
  filename: output.video.filename,
  video_url: output.video.download_url,
  randomization: output.video.randomization,
  processing_time: output.processing_time
}];
