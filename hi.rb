require 'sinatra'

get '/hi' do
  `python knit/PDDemulate.py . /dev/cu.usbserial-FTX20UXH`
  #"Hello World!asdf"
end