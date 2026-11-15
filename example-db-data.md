# Example data structure of an Album

```
MariaDB [gallery3]> select * from items where name="johnson-junior" limit 1\G
*************************** 1. row ***************************
                 id: 132
album_cover_item_id: 16241
           captured: NULL
            created: 1125366490
        description: 
             height: NULL
           left_ptr: 44295
              level: 3
          mime_type: NULL
               name: johnson-junior
           owner_id: 8
          parent_id: 19
           rand_key: 0.1892340000
`relative_path_cache`: 1993/johnson-junior
 relative_url_cache: 1993/johnson-junior
       resize_dirty: 1
      resize_height: NULL
       resize_width: NULL
          right_ptr: 44368
               slug: johnson-junior
        sort_column: weight
         sort_order: ASC
        thumb_dirty: 0
       thumb_height: 134
        thumb_width: 200
              title: Johnson Junior High
               type: album
            updated: 1449605422
         view_count: 125
             weight: 132
              width: NULL
             view_1: 0
             view_2: 0
             view_3: 1
             view_5: 1
```

# Example data structure of an Image

```
MariaDB [gallery3]> select * from items where parent_id=132\G

                 id: 16216
album_cover_item_id: NULL
           captured: NULL
            created: 1355750153
        description: 6th grade english class. (me, joe, fred, alice, bob, alex)
             height: 981
           left_ptr: 44296
              level: 4
          mime_type: image/jpeg
               name: middleschool_mg0001.jpg
           owner_id: 8
          parent_id: 132
           rand_key: 0.0808660000
relative_path_cache: 1993/johnson-junior/middleschool_mg0001.jpg
 relative_url_cache: 1993/johnson-junior/middleschool_mg0001
       resize_dirty: 0
      resize_height: 518
       resize_width: 640
          right_ptr: 44297
               slug: middleschool_mg0001
        sort_column: created
         sort_order: ASC
        thumb_dirty: 0
       thumb_height: 162
        thumb_width: 200
              title: 6th grade english class. (me, joe, fred, alice, bob, alex)
               type: photo
            updated: 1355750154
         view_count: 10
             weight: 16216
              width: 1211
             view_1: 0
             view_2: 0
             view_3: 1
             view_5: 1
```

# Example data structure of a comment

```
MariaDB [gallery3]> select * from comments limit 1\G
*************************** 1. row ***************************
                  author_id: 1
                    created: 1201114185
                guest_email: unknown@nobody.com
                 guest_name: Anonymous coward
                  guest_url: NULL
                         id: 1
                    item_id: 949
 server_http_accept_charset: NULL
server_http_accept_encoding: NULL
server_http_accept_language: NULL
         server_http_accept: NULL
     server_http_connection: NULL
           server_http_host: 203.0.113.100
        server_http_referer: NULL
     server_http_user_agent: NULL
        server_query_string: NULL
         server_remote_addr: NULL
         server_remote_host: NULL
         server_remote_port: NULL
                      state: published
                       text: AZ Mom
TOTALLY AWESOME!!  Thanks for sharing.  Now...I need to get a version that I can get a print of.
Kathy
                    updated: 1355815963
```

# Example data structure of users

```
MariaDB [gallery3]> select * from users limit 3\G
*************************** 1. row ***************************
         id: 1
       name: guest
  full_name: Guest User
   password:
login_count: 0
 last_login: 0
      email: NULL
      admin: 0
      guest: 1
       hash: NULL
        url: NULL
     locale: NULL
*************************** 2. row ***************************
         id: 2
       name: admin
  full_name: Gallery Administrator
   password: REDACTED
login_count: 5
 last_login: 1385948468
      email: admin@example.com
      admin: 1
      guest: 0
       hash: NULL
        url:
     locale: NULL
*************************** 3. row ***************************
         id: 3
       name: jdoe
  full_name: John Doe
   password: REDACTED
login_count: 92
 last_login: 1767719470
      email: jdoe@example.com
      admin: 1
      guest: 0
       hash: NULL
        url: NULL
     locale: NULL
3 rows in set (0.001 sec)
```

# Example data structure of tags

```
MariaDB [gallery3]> select * from items_tags limit 1\G
*************************** 1. row ***************************
     id: 1
item_id: 155
 tag_id: 1
1 row in set (0.002 sec)
MariaDB [gallery3]> select * from tags where id=1\G
*************************** 1. row ***************************
   id: 1
 name: Lego
count: 1
1 row in set (0.002 sec)
```
