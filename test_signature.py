from app.activitypub.signature import HttpSignature
from app.utils import file_get_contents

body_1 = file_get_contents('testing_data/body_1.json')
body_2 = file_get_contents('testing_data/body_2.json')
body_3 = file_get_contents('testing_data/body_3.json')
digest_1 = file_get_contents('testing_data/digest_1')
digest_2 = file_get_contents('testing_data/digest_2')
digest_3 = file_get_contents('testing_data/digest_3')
signature_1 = file_get_contents('testing_data/signature_1')
signature_2 = file_get_contents('testing_data/signature_2')
signature_3 = file_get_contents('testing_data/signature_3')

assert digest_1 == HttpSignature.calculate_digest(body_1.encode())
assert digest_2 == HttpSignature.calculate_digest(body_2.encode())
assert digest_3 == HttpSignature.calculate_digest(body_3.encode())

parsed = HttpSignature.parse_signature(signature_1)
original_signature = sorted(signature_1.split(','))
processed_signature = sorted(HttpSignature.compile_signature(parsed).split(','))
assert original_signature == processed_signature

parsed = HttpSignature.parse_signature(signature_2)
original_signature = sorted(signature_2.split(','))
processed_signature = sorted(HttpSignature.compile_signature(parsed).split(','))
assert original_signature == processed_signature

parsed = HttpSignature.parse_signature(signature_3)
original_signature = sorted(signature_3.split(','))
processed_signature = sorted(HttpSignature.compile_signature(parsed).split(','))
assert original_signature == processed_signature



print('Done')
