import os


def public_key():
    if not os.path.exists('./public.pem'):
        os.system('openssl genrsa -out private.pem 2048')
        os.system('openssl rsa -in private.pem -outform PEM -pubout -out public.pem')
    else:
        publicKey = open('./public.pem', 'r').read()
        PUBLICKEY = publicKey.replace('\n', '\\n')  # JSON-LD doesn't want to work with linebreaks,
        # but needs the \n character to know where to break the line ;)
        return PUBLICKEY
