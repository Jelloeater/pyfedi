import multiprocessing

workers = multiprocessing.cpu_count() * 2 + 1
threads = multiprocessing.cpu_count() * 2 + 1

worker_tmp_dir = '/dev/shm'

bind = '127.0.0.1:5000'
umask = 0o007
reload = False

#logging
accesslog = '-'
errorlog = '-'

max_requests = 500
max_requests_jitter = 50
