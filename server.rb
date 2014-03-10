require 'sinatra'
require 'Open3'
require 'haml'

get '/upload' do
  haml :upload
end

post '/upload' do
  filename = 'uploads/' + params['myfile'][:filename]
  File.open(filename, "w") do |f|
    f.write(params['myfile'][:tempfile].read)
  end

  result = `python img2track.py #{filename} . 1.5 60`
  puts result
  stdin, stdout, stderr = Open3.popen3("python knit/PDDemulate.py . /dev/cu.usbserial-FTX20UXH")
  return "turn on machine, press CE 551, STEP, 1, STEP to load pattern! \nPattern will be available as pattern 901."
end
