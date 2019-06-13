import os
import random

path = os.getcwd()
dir_path = [path+'image']
dir_path += [path+'/trimap/face-tri-10000/']
dir_path += [path+'/trimap/fill_trimap_10000/3/']
dir_path += [path+'/trimap/fill_trimap_10000/4/']
dir_path += [path+'/trimap/fill_trimap_10000/5/']
dir_path += [path+'/result10000/UI/alpha/']
dir_path += [path+'/result10000/UI/trimap/']



add = ['{}.jpg', '{}.png', '{}.png', '{}.png', '{}.png', '{}.png', '{}.png']

imgs = [i.split('.')[0] for i in os.listdir(dir_path[1])]
random.shuffle(imgs)
for i in imgs:
    s = []
    for j, ad in zip(dir_path, add):
        img = ad.format(i)
        path = os.path.join(j, img)
        s.append(path)
    print(s)