# -*- coding:utf-8 -*- 


#
# Interface to the AVT Vimba SDK
#


#
# External dependencies
#
import os
import Queue
import ctypes as ct
import numpy as np


#
# Global access to the Vimba library
#
vimba = None


#
# Initialize the Vimba library
#
def VmbStartup() :
	
	# Get Vimba installation directory
	vimba_path = "/" + "/".join(os.environ.get("GENICAM_GENTL64_PATH").split("/")[1:-3])
	vimba_path += "/VimbaC/DynamicLib/x86_64bit/libVimbaC.so"
		
	# Load Vimba library
	global vimba
	vimba = ct.cdll.LoadLibrary( vimba_path )

	# Initialize the library
	vimba.VmbStartup()
		
	# Send discovery packet to GigE cameras
	vimba.VmbFeatureCommandRun( ct.c_void_p(1), "GeVDiscoveryAllOnce" )
	

#
# Release the Vimba library
#
def VmbShutdown() :
	
	# Release the library
	vimba.VmbShutdown()


#
# Vimba frame structure
#
class VmbFrame( ct.Structure ) :
	
	#
	# VmbFrame structure fields
	#
	_fields_ = [('buffer', ct.POINTER(ct.c_char)),
			('bufferSize', ct.c_uint32),
			('context', ct.c_void_p * 4),
			('receiveStatus', ct.c_int32),
			('receiveFlags', ct.c_uint32),
			('imageSize', ct.c_uint32),
			('ancillarySize', ct.c_uint32),
			('pixelFormat', ct.c_uint32),
			('width', ct.c_uint32),
			('height', ct.c_uint32),
			('offsetX', ct.c_uint32),
			('offsetY', ct.c_uint32),
			('frameID', ct.c_uint64),
			('timestamp', ct.c_uint64)]
	
	#
	# Initialize the image buffer
	#
	def __init__( self, frame_size ) :

		self.buffer = ct.create_string_buffer( frame_size )
		self.bufferSize = ct.c_uint32( frame_size )


#
# Vimba camera
#
class VmbCamera( object ) :
	
	#
	# Initialize the camera
	#
	def __init__( self, id_string ) :
		
		# Camera handle
		self.handle = ct.c_void_p()

		# Camera ID (serial number, IP address...)
		self.id_string = id_string
		
		# Connect the camera
		vimba.VmbCameraOpen( self.id_string, 1, ct.byref(self.handle) )

		# Adjust packet size automatically
		vimba.VmbFeatureCommandRun( self.handle, "GVSPAdjustPacketSize" )
		
		# Configure the camera
		vimba.VmbFeatureEnumSet( self.handle, "AcquisitionMode", "Continuous" )
		vimba.VmbFeatureEnumSet( self.handle, "TriggerSource", "Freerun" )
		vimba.VmbFeatureEnumSet( self.handle, "PixelFormat", "Mono8" )

		# Query image parameters
		tmp_value = ct.c_int()
		vimba.VmbFeatureIntGet( self.handle, "Width", ct.byref(tmp_value) )
		self.width = tmp_value.value
		vimba.VmbFeatureIntGet( self.handle, "Height", ct.byref(tmp_value) )
		self.height = tmp_value.value
		vimba.VmbFeatureIntGet( self.handle, "PayloadSize", ct.byref(tmp_value) )
		self.payloadsize = tmp_value.value
		
		# Default image parameters of our cameras (AVT Manta G504B) for debug purpose
#		self.width = 2452
#		self.height = 2056
#		self.payloadsize = 5041312

		#
		# rename to frames
		#
		# Initialize the image
		self.image_queue = Queue.Queue()
	
	#
	# Disconnect the camera
	#
	def Disconnect( self ) :
		
		# Close the camera
		vimba.VmbCameraClose( self.handle )

	#
	# Start the acquisition
	#
	def CaptureStart( self, image_callback_function ) :

		#
		# No self. needed
		#
		# Initialize frame buffer
		self.frame_number = 3
		self.frames = []
		for i in range( self.frame_number ) :
			self.frames.append( VmbFrame( self.payloadsize ) )
		
		# Register the external image callback function
		self.image_callback_function = image_callback_function
		
		# Register the internal frame callback function
		self.frame_callback_function = ct.CFUNCTYPE( None, ct.c_void_p, ct.POINTER(VmbFrame) )( self.FrameCallback )

		# Announce the frames
		for i in range( self.frame_number ) :
			vimba.VmbFrameAnnounce( self.handle, ct.byref(self.frames[i]), ct.sizeof(self.frames[i]) )

		# Start capture engine
		vimba.VmbCaptureStart( self.handle )
		
		# Queue the frames
		for i in range( self.frame_number ) :
			vimba.VmbCaptureFrameQueue( self.handle, ct.byref(self.frames[i]), self.frame_callback_function )

		# Start acquisition
		vimba.VmbFeatureCommandRun( self.handle, "AcquisitionStart" )

	#
	# Stop the acquisition
	#
	def CaptureStop( self ) :

		# Stop acquisition
		vimba.VmbFeatureCommandRun( self.handle, "AcquisitionStop" )

		# Flush the frame queue
		vimba.VmbCaptureQueueFlush( self.handle )

		# Stop capture engine
		vimba.VmbCaptureEnd( self.handle )

		# Revoke frames
		vimba.VmbFrameRevokeAll( self.handle )
		
	#
	# Frame callback function called by Vimba
	#
	def FrameCallback( self, camera, frame ) :

		# Check frame validity
		if not frame.contents.receiveStatus :
			
			# Convert frames to numpy arrays
			image = np.fromstring( frame.contents.buffer[ 0 : self.payloadsize ], dtype=np.uint8 )
			image = image.reshape( self.height, self.width )
			self.image_queue.put( image )
			
			# Process the image with the provided function
			self.image_callback_function()

		# Requeue the frame so it can be filled again
		vimba.VmbCaptureFrameQueue( camera, frame, self.frame_callback_function )
		
		
	#
	# Queue a given frame
	#
	def QueueFrame( self, frame ) :
		
		# Queue the frame so it can be filled again
		vimba.VmbCaptureFrameQueue( self.handle, frame, self.frame_callback_function )
		
		
	#
	# Lock the thread and return the image
	#
	def GetImage( self ) :
		
		#
		# Change to get Frame
		#
		image = self.image_queue.get()
		self.image_queue.task_done()
		return image


#
# Convert a Vimba camera frame to a numpy array
#
def Frame2Array( frame ) :
	
	width = frame.contents.width
	height = frame.contents.height
	payloadsize = frame.contents.payloadsize
	return np.fromstring( frame.contents.buffer[ 0 : payloadsize ], dtype=np.uint8 ).reshape( height, width )
