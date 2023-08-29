from datetime import datetime

from app import db
from app.models import Community, File, BannedInstances
from app.utils import get_request


def search_for_community(address: str):
    if address.startswith('!'):
        name, server = address[1:].split('@')

        banned = BannedInstances.query.filter_by(domain=server).first()
        if banned:
            reason = f" Reason: {banned.reason}" if banned.reason is not None else ''
            raise Exception(f"{server} is blocked.{reason}")    # todo: create custom exception class hierarchy

        already_exists = Community.query.filter_by(ap_id=address[1:]).first()
        if already_exists:
            return already_exists

        # Look up the profile address of the community using WebFinger
        # todo: try, except block around every get_request
        webfinger_data = get_request(f"https://{server}/.well-known/webfinger",
                                     params={'resource': f"acct:{address[1:]}"})
        if webfinger_data.status_code == 200:
            webfinger_json = webfinger_data.json()
            for links in webfinger_json['links']:
                if 'rel' in links and links['rel'] == 'self':   # this contains the URL of the activitypub profile
                    type = links['type'] if 'type' in links else 'application/activity+json'
                    # retrieve the activitypub profile
                    community_data = get_request(links['href'], headers={'Accept': type})
                    # to see the structure of the json contained in community_data, do a GET to https://lemmy.world/c/technology with header Accept: application/activity+json
                    if community_data.status_code == 200:
                        community_json = community_data.json()
                        if community_json['type'] == 'Group':
                            community = Community(name=community_json['preferredUsername'],
                                                  title=community_json['name'],
                                                  description=community_json['summary'],
                                                  nsfw=community_json['sensitive'],
                                                  restricted_to_mods=community_json['postingRestrictedToMods'],
                                                  created_at=community_json['published'],
                                                  last_active=community_json['updated'],
                                                  ap_id=f"{address[1:]}",
                                                  ap_public_url=community_json['id'],
                                                  ap_profile_id=community_json['id'],
                                                  ap_followers_url=community_json['followers'],
                                                  ap_inbox_url=community_json['endpoints']['sharedInbox'],
                                                  ap_fetched_at=datetime.utcnow(),
                                                  ap_domain=server,
                                                  public_key=community_json['publicKey']['publicKeyPem'],
                                                  # language=community_json['language'][0]['identifier'] # todo: language
                                                  )
                            if 'icon' in community_json:
                                # todo: retrieve icon, save to disk, save more complete File record
                                icon = File(source_url=community_json['icon']['url'])
                                community.icon = icon
                                db.session.add(icon)
                            if 'image' in community_json:
                                # todo: retrieve image, save to disk, save more complete File record
                                image = File(source_url=community_json['image']['url'])
                                community.image = image
                                db.session.add(image)
                            db.session.add(community)
                            db.session.commit()
                            return community
        return None
