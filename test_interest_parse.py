from app.cli import parse_communities
from app.utils import file_get_contents

interests = file_get_contents('interests.txt')
communities = parse_communities(interests, 'gaming')
print(communities)

communities = parse_communities(interests, 'chilling')
print(communities)

communities = parse_communities(interests, 'mental health')
print(communities)
