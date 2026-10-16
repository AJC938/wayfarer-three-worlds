import argparse
import math
import random
import time

import pygame

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

WIDTH, HEIGHT, FPS = 1000, 640, 60
GAME_NAME = "Wayfarer: Three Worlds"
INITIAL_WINDOW_SIZE = (1100, 704)
MIN_WINDOW_SIZE = (640, 410)
GROUND_Y = 560
WORLD_WIDTH = 2800
BAUD = 9600
PLAYER_SPEED = 265
PLAYER_ACCEL = 1900
PLAYER_BRAKE = 2600
GRAVITY = 1450
JUMP_SPEED = 570
JUMP_BUFFER = 0.14
COYOTE_TIME = 0.11
JOYSTICK_CENTER = 512
DEAD_ZONE = 65
JUMP_THRESHOLD = 190
MOVE_AXIS = "y"          # Verified A1 axis: left low, right high.
JUMP_AXIS = "x"          # Verified A0 axis: up reads high.

LEVELS = [
    {"name":"SUNLIT GROVE", "sky":(15,24,43), "far":(27,49,65), "ground":(43,79,70), "accent":(114,223,167), "platforms":[(260,465,155),(510,390,150),(790,475,180),(1080,405,165),(1400,465,180),(1710,390,165),(2040,460,190),(2350,405,180)], "coins":[(305,425),(555,350),(620,350),(840,435),(1140,365),(1450,425),(1760,350),(2100,420),(2410,365)], "hazards":[(650,540,90),(1270,540,100),(1900,540,110)], "enemies":[(430,514),(920,514),(1540,514),(2190,514)], "boss":(2540,470)},
    {"name":"EMBER CANYON", "sky":(35,17,29), "far":(77,34,43), "ground":(105,52,41), "accent":(255,158,90), "platforms":[(220,465,145),(455,380,135),(700,455,150),(965,350,145),(1210,440,140),(1460,365,150),(1730,465,160),(2010,365,150),(2260,440,150)], "coins":[(260,425),(500,340),(750,415),(1010,310),(1260,400),(1510,325),(1780,425),(2060,325),(2310,400)], "hazards":[(360,540,105),(820,540,115),(1110,540,110),(1590,540,100),(2150,540,100)], "enemies":[(600,514),(1040,514),(1370,514),(1850,514),(2360,514)], "boss":(2540,465)},
    {"name":"FROSTBOUND KEEP", "sky":(10,22,43), "far":(24,52,78), "ground":(43,83,112), "accent":(126,220,255), "platforms":[(230,460,155),(490,350,145),(740,440,140),(980,350,140),(1210,415,150),(1470,325,140),(1710,460,150),(1960,360,140),(2190,425,145),(2390,340,145)], "coins":[(280,420),(540,310),(785,400),(1025,310),(1260,375),(1510,285),(1760,420),(2000,320),(2240,385),(2435,300)], "hazards":[(400,540,100),(850,540,110),(1350,540,105),(1880,540,100),(2300,540,80)], "enemies":[(630,514),(1100,514),(1610,514),(2070,514),(2460,514)], "boss":(2540,455)},
]
WHITE=(239,247,255); MUTED=(161,184,207); GOLD=(255,211,105); RED=(255,97,112)


def clamp(value, low, high):
    return max(low, min(high, value))


class ArduinoLink:
    """Non-blocking CSV input and change-driven state/event output."""
    def __init__(self, port=None, keyboard_only=False):
        self.requested_port=port; self.keyboard_only=keyboard_only
        self.connection=None; self.port_name=None; self.buffer=b""
        self.x=512; self.y=512; self.button=0; self.last_packet=0
        self.status="Keyboard only" if keyboard_only else "Arduino disconnected"
        self.last_try=0; self.last_sent=None; self.opening=False
        if not keyboard_only: self.connect()

    @property
    def connected(self): return self.connection is not None

    def connect(self):
        if serial is None:
            self.status="Keyboard only (install pyserial)"; return
        ports=[p.device for p in list_ports.comports()]
        if self.requested_port:
            candidates=[self.requested_port]
        else:
            likely=[p.device for p in list_ports.comports() if any(s in ((p.description or "")+(p.manufacturer or "")).lower() for s in ("arduino","usb serial","ch340","cp210"))]
            candidates=likely+[p for p in ports if p not in likely]
        self.last_try=time.monotonic()
        for name in candidates:
            try:
                self.connection=serial.Serial(name,BAUD,timeout=0,write_timeout=0)
                self.last_sent=None
                self.port_name=name; self.buffer=b""; self.opening=True
                self.status=f"Connecting {name}..."; return
            except (serial.SerialException,OSError):
                continue
        self.status=f"Port unavailable: {self.requested_port}" if self.requested_port else "Arduino disconnected"

    def update(self):
        if not self.connection:
            if not self.keyboard_only and time.monotonic()-self.last_try>3: self.connect()
            return
        try:
            if self.opening:
                if time.monotonic()-self.last_try<1.4: return
                self.connection.reset_input_buffer(); self.opening=False
            n=self.connection.in_waiting
            if n: self.buffer+=self.connection.read(min(n,512))
            if len(self.buffer)>2048: self.buffer=self.buffer[-512:]
            while b"\n" in self.buffer:
                raw,self.buffer=self.buffer.split(b"\n",1)
                try:
                    fields=raw.decode("ascii").strip().split(",")
                    if len(fields)!=3: continue
                    x,y,button=map(int,fields)
                    if 0<=x<=1023 and 0<=y<=1023 and button in (0,1):
                        self.x,self.y,self.button=x,y,button; self.last_packet=time.monotonic()
                except (ValueError,UnicodeDecodeError): pass
            self.status=f"Arduino {self.port_name}" if time.monotonic()-self.last_packet<1.2 else f"No input: {self.port_name}"
        except (serial.SerialException,OSError):
            self.close(); self.status="Arduino disconnected"; self.last_try=time.monotonic()

    def send_state(self, alive, level, coins, hp, boss, event="-"):
        if not self.connection or self.opening: return
        row=(int(alive),level,coins,hp,boss,event)
        if row==self.last_sent: return
        payload=f"S,{row[0]},{row[1]},{row[2]},{row[3]},{row[4]},{row[5]}\n".encode("ascii")
        try:
            self.connection.write(payload); self.last_sent=row
        except (serial.SerialException,OSError):
            self.close(); self.status="Arduino disconnected"; self.last_try=time.monotonic()

    def close(self):
        if self.connection:
            try:self.connection.close()
            except (serial.SerialException,OSError):pass
        self.connection=None; self.opening=False


class Player:
    def __init__(self):
        self.rect=pygame.Rect(70,GROUND_Y-48,34,48); self.vx=0.; self.vy=0.
        self.grounded=True; self.hp=3; self.invuln=0.; self.facing=1; self.anim=0.
        self.coyote=COYOTE_TIME; self.jump_buffer=0.; self.safe_position=self.rect.topleft


class Platformer:
    def __init__(self,link):
        pygame.init(); pygame.display.set_caption(f"{GAME_NAME} | Arduino Platformer")
        self.window=pygame.display.set_mode(INITIAL_WINDOW_SIZE,pygame.RESIZABLE)
        self.windowed_size=INITIAL_WINDOW_SIZE; self.fullscreen=False
        # Draw the whole game at a fixed logical resolution, then scale it into
        # the resizable display so world geometry and UI keep their proportions.
        self.screen=pygame.Surface((WIDTH,HEIGHT)).convert(); self.clock=pygame.time.Clock()
        self.font=pygame.font.Font(None,26); self.title=pygame.font.Font(None,68); self.large=pygame.font.Font(None,58); self.small=pygame.font.Font(None,21)
        self.overlay_veil=pygame.Surface((WIDTH,HEIGHT),pygame.SRCALPHA); self.overlay_veil.fill((3,7,18,190))
        self.link=link; self.state="MENU"; self.level_index=0; self.coins=0; self.camera=0; self.particles=[]; self.message_event="-"; self.event_timer=0; self.jump_was_down=False
        self.damage_flash=0.
        self.stars=[(random.randrange(WORLD_WIDTH),random.randrange(HEIGHT),random.choice((1,1,2))) for _ in range(110)]
        self.load_level(0)
        self.state="MENU"
        self.push_state()

    def toggle_fullscreen(self):
        if self.fullscreen:
            self.fullscreen=False
            self.window=pygame.display.set_mode(self.windowed_size,pygame.RESIZABLE)
        else:
            self.windowed_size=self.window.get_size()
            self.window=pygame.display.set_mode((0,0),pygame.FULLSCREEN)
            self.fullscreen=True

    def present(self):
        win_w,win_h=self.window.get_size()
        scale=min(win_w/WIDTH,win_h/HEIGHT)
        view_w=max(1,round(WIDTH*scale)); view_h=max(1,round(HEIGHT*scale))
        viewport=pygame.Rect((win_w-view_w)//2,(win_h-view_h)//2,view_w,view_h)
        self.window.fill((0,0,0))
        frame=pygame.transform.smoothscale(self.screen,viewport.size)
        self.window.blit(frame,viewport)
        pygame.display.flip()

    def load_level(self,index):
        self.level_index=index; data=LEVELS[index]; self.player=Player(); self.camera=0
        self.platforms=[pygame.Rect(x,y,w,18) for x,y,w in data["platforms"]]
        self.hazards=[pygame.Rect(x,y,w,GROUND_Y-y) for x,y,w in data["hazards"]]
        self.coins_world=[pygame.Rect(x,y,18,22) for x,y in data["coins"]]
        # Keep each patrol near its authored encounter instead of letting it
        # drift across the entire world over time.
        self.enemies=[[pygame.Rect(x,y,34,46),1,0,x-72,x+72] for x,y in data["enemies"]]
        bx,by=data["boss"]; self.boss=pygame.Rect(bx,by,76,90); self.boss_hp=4+index*2; self.boss_max=self.boss_hp; self.boss_active=False; self.boss_cool=2.0; self.boss_projectiles=[]; self.level_elapsed=0
        self.pickup_anim=0; self.message_event="LEVEL" if index else "-"; self.event_timer=0.6 if index else 0
        self.enter_state("PLAYING")

    def enter_state(self,state,event=None):
        self.state=state
        if event:self.emit(event)
        self.push_state()

    def emit(self,event): self.message_event=event; self.event_timer=0.75; self.link.last_sent=None

    def push_state(self):
        boss=2 if self.boss_hp<=0 else (1 if self.boss_active else 0)
        self.link.send_state(self.state not in ("PLAYER_DEAD","GAME_OVER"),self.level_index+1,self.coins,self.player.hp,boss,self.message_event if self.event_timer>0 else "-")

    def text(self,s,font,color,center):
        surf=font.render(s,True,color); self.screen.blit(surf,surf.get_rect(center=center))

    def start_game(self): self.coins=0; self.load_level(0); self.enter_state("PLAYING")

    def hurt(self):
        p=self.player
        if p.invuln>0:return
        p.hp-=1; p.invuln=1.25; self.damage_flash=.16; self.burst(p.rect.center,RED,15); self.emit("DAMAGE")
        if p.hp<=0:self.enter_state("PLAYER_DEAD","DEATH")

    def burst(self,pos,color,count=10):
        for _ in range(count): self.particles.append([float(pos[0]),float(pos[1]),random.uniform(-120,120),random.uniform(-180,40),random.uniform(.25,.65),color])

    def update_particles(self,dt):
        self.damage_flash=max(0.,self.damage_flash-dt)
        for particle in self.particles:
            particle[0]+=particle[2]*dt; particle[1]+=particle[3]*dt
            particle[3]+=220*dt; particle[4]-=dt
        self.particles[:]=[particle for particle in self.particles if particle[4]>0]

    def update(self,dt,keys):
        self.link.update(); self.event_timer=max(0,self.event_timer-dt); self.update_particles(dt)
        if self.state not in ("PLAYING","BOSS_FIGHT"): return
        p=self.player; data=LEVELS[self.level_index]; self.level_elapsed+=dt; p.invuln=max(0,p.invuln-dt); p.anim+=dt*12
        p.coyote=max(0.,p.coyote-dt); p.jump_buffer=max(0.,p.jump_buffer-dt)
        axis=0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:axis-=1
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:axis+=1
        if self.link.connected and time.monotonic()-self.link.last_packet<1.2:
            move_reading = self.link.y if MOVE_AXIS == "y" else self.link.x
            raw = move_reading - JOYSTICK_CENTER
            axis=0 if abs(raw)<=DEAD_ZONE else math.copysign(min(1,(abs(raw)-DEAD_ZONE)/330),raw)
        target_vx=axis*PLAYER_SPEED
        response=PLAYER_ACCEL if axis and (p.vx==0 or p.vx*target_vx>=0) else PLAYER_BRAKE
        p.vx+=clamp(target_vx-p.vx,-response*dt,response*dt)
        if axis:p.facing=1 if axis>0 else -1
        jump_reading = self.link.x if JUMP_AXIS == "x" else self.link.y
        jump_down=keys[pygame.K_UP] or keys[pygame.K_w] or keys[pygame.K_SPACE] or (self.link.connected and jump_reading > JOYSTICK_CENTER+JUMP_THRESHOLD and time.monotonic()-self.link.last_packet<1.2)
        jump_pressed=jump_down and not self.jump_was_down
        self.jump_was_down=jump_down
        if jump_pressed:p.jump_buffer=JUMP_BUFFER
        if p.grounded:p.coyote=COYOTE_TIME
        if p.jump_buffer>0 and p.coyote>0:
            p.vy=-JUMP_SPEED; p.grounded=False; p.coyote=0.; p.jump_buffer=0.
            self.burst((p.rect.centerx,p.rect.bottom),data["accent"],7)
        p.rect.x+=round(p.vx*dt); p.rect.x=clamp(p.rect.x,0,WORLD_WIDTH-p.rect.width)
        p.vy=min(850,p.vy+GRAVITY*dt); p.rect.y+=int(p.vy*dt); p.grounded=False
        # Land on the floor and one-way ledges.
        if p.rect.bottom>=GROUND_Y and not any(p.rect.colliderect(h) for h in self.hazards):p.rect.bottom=GROUND_Y; p.vy=0; p.grounded=True
        for plat in self.platforms:
            if p.vy>=0 and p.rect.colliderect(plat) and p.rect.bottom-p.vy*dt<=plat.top+8:
                p.rect.bottom=plat.top; p.vy=0; p.grounded=True
        if any(p.rect.colliderect(h) for h in self.hazards) or p.rect.top>HEIGHT+60:
            self.hurt()
            if self.state=="PLAYER_DEAD":return
            p.rect.topleft=p.safe_position; p.vx=0.; p.vy=0.; p.grounded=True
        elif p.grounded:
            p.safe_position=p.rect.topleft
        # Coins.
        for coin in self.coins_world[:]:
            if p.rect.colliderect(coin):self.coins+=1; self.coins_world.remove(coin); self.burst(coin.center,GOLD,9); self.emit("COIN")
        # Patrol enemies; stomp them from above, otherwise take damage.
        for enemy in self.enemies[:]:
            r,direction,timer,left,right=enemy; r.x+=round(direction*65*dt); enemy[2]+=dt
            if r.left<left:r.left=left; enemy[1]=1
            elif r.right>right:r.right=right; enemy[1]=-1
            if p.rect.colliderect(r):
                if p.vy>50 and p.rect.bottom-r.top<24:
                    p.rect.bottom=r.top; p.vy=-JUMP_SPEED*.55; self.enemies.remove(enemy); self.burst(r.center,data["accent"],12); self.emit("ENEMY")
                else:self.hurt()
                if self.state=="PLAYER_DEAD":return
        # Boss activates at the level's end; jump on its top to damage it.
        if p.rect.centerx>self.boss.x-200 and not self.boss_active and self.boss_hp>0:
            self.boss_active=True; self.enter_state("BOSS_FIGHT","BOSS")
        if self.boss_active and self.boss_hp>0:
            self.boss_cool-=dt
            if self.boss_cool<=0:
                self.boss_cool=(1.55 if self.level_index==0 else (1.15 if self.level_index==1 else .9))
                if self.level_index==0:
                    # Grove guardian: slow, easy-to-read horizontal bolt.
                    self.boss_projectiles.append([pygame.Rect(self.boss.left-14,self.boss.centery-8,22,16),-225,0])
                elif self.level_index==1:
                    # Canyon guardian: a single aimed shot, telegraphed by its wind-up.
                    start_y=self.boss.centery
                    dx=p.rect.centerx-self.boss.centerx; dy=p.rect.centery-start_y
                    distance=max(1,math.hypot(dx,dy)); speed=260
                    self.boss_projectiles.append([pygame.Rect(self.boss.left-14,start_y-8,22,16),dx/distance*speed,dy/distance*speed])
                else:
                    # Final guardian: a three-lane fan that leaves gaps to dodge through.
                    for offset,vy in ((-15,-145),(0,0),(15,145)):
                        self.boss_projectiles.append([pygame.Rect(self.boss.left-14,self.boss.centery+offset-8,22,16),-270,vy])
            for shot in self.boss_projectiles[:]:
                shot[0].x+=round(shot[1]*dt); shot[0].y+=round(shot[2]*dt)
                if shot[0].right<self.camera-40 or shot[0].top>HEIGHT+20 or shot[0].bottom<-20:self.boss_projectiles.remove(shot)
                elif shot[0].colliderect(p.rect):self.boss_projectiles.remove(shot); self.hurt()
                if self.state=="PLAYER_DEAD":return
            if p.rect.colliderect(self.boss):
                if p.vy>40 and p.rect.bottom-self.boss.top<28:
                    p.rect.bottom=self.boss.top; p.vy=-JUMP_SPEED*.58; self.boss_hp-=1; self.burst(self.boss.midtop,data["accent"],15); self.emit("BOSS_HIT")
                    if self.boss_hp<=0:
                        self.burst(self.boss.center,GOLD,35); self.boss_active=False; self.boss_projectiles.clear(); self.enter_state("LEVEL_CLEAR","BOSS_DOWN")
                else:self.hurt()
                if self.state=="PLAYER_DEAD":return
        self.camera=int(clamp(p.rect.centerx-WIDTH*.38,0,WORLD_WIDTH-WIDTH))
        if self.state in ("PLAYING","BOSS_FIGHT"):self.push_state()

    def draw_background(self,data):
        self.screen.fill(data["sky"])
        ticks=pygame.time.get_ticks()
        for i,(x,y,r) in enumerate(self.stars):
            sx=int((x-self.camera*.22)%WIDTH); shimmer=18 if (ticks//360+i)%5==0 else 0
            pygame.draw.circle(self.screen,(min(255,120+shimmer),min(255,153+shimmer),min(255,190+shimmer)),(sx,y),r)
        # A restrained palette glow and silhouettes give each world a distinct horizon.
        glow=data["accent"]
        pygame.draw.circle(self.screen,tuple(channel//8 for channel in glow),(800,145),94)
        for i in range(-1,9):
            x=(i*280-int(self.camera*.15))%(WIDTH+340)-170
            base=474+(i%3)*17
            if self.level_index==0:
                pygame.draw.rect(self.screen,(19,48,53),(x+43,base-68,17,82),border_radius=7)
                for ox,oy,radius in ((35,-63,29),(68,-82,37),(98,-57,29)):
                    pygame.draw.circle(self.screen,(22,58,61),(x+ox,base+oy),radius)
                pygame.draw.circle(self.screen,(33,78,71),(x+68,base-82),21)
            elif self.level_index==1:
                pygame.draw.polygon(self.screen,(67,35,42),[(x,base),(x+28,base-107),(x+58,base),(x+82,base-72),(x+117,base)])
                pygame.draw.polygon(self.screen,(88,43,45),[(x+25,base-94),(x+29,base-107),(x+58,base),(x+45,base)])
            else:
                pygame.draw.polygon(self.screen,(23,50,77),[(x+8,base),(x+48,base-126),(x+66,base-44),(x+104,base-99),(x+131,base)])
                pygame.draw.polygon(self.screen,(34,71,99),[(x+48,base-126),(x+66,base-44),(x+57,base-25)])
        # Layered distant hills.
        for i in range(-1,7):
            x=(i*230-int(self.camera*.38))% (WIDTH+260)-130
            pygame.draw.ellipse(self.screen,data["far"],(x,360+(i%3)*34,300,250))
        pygame.draw.rect(self.screen,data["ground"],(0,GROUND_Y,WIDTH,HEIGHT-GROUND_Y))
        pygame.draw.line(self.screen,data["accent"],(0,GROUND_Y),(WIDTH,GROUND_Y),3)
        for h in self.hazards:
            r=h.move(-self.camera,0); pygame.draw.rect(self.screen,(42,24,33),r)
            for x in range(r.left,r.right,18):pygame.draw.polygon(self.screen,(255,111,82),[(x,GROUND_Y),(x+9,GROUND_Y-16),(x+18,GROUND_Y)])
        for plat in self.platforms:
            r=plat.move(-self.camera,0); pygame.draw.rect(self.screen,(24,35,49),r,border_radius=5); pygame.draw.rect(self.screen,data["accent"],(r.x,r.y,r.w,6),border_radius=3)
            pygame.draw.line(self.screen,(100,120,136),(r.x+12,r.y+12),(r.right-12,r.y+12),1)

    def draw_character(self,r):
        if self.player.invuln>0 and int(self.player.invuln*12)%2:return
        x=r.x-self.camera; y=r.y
        # compact adventurer, with scarf and animated feet
        pygame.draw.ellipse(self.screen,(0,0,0,80),(x-5,y+40,44,10))
        pygame.draw.polygon(self.screen,(181,76,88),[(x+8,y+27),(x-6,y+32+int(math.sin(self.player.anim)*3)),(x+11,y+37)])
        pygame.draw.rect(self.screen,(24,42,66),(x+5,y+19,25,27),border_radius=8)
        pygame.draw.rect(self.screen,(88,201,186),(x+7,y+22,21,20),border_radius=7)
        pygame.draw.line(self.screen,(174,246,216),(x+10,y+25),(x+23,y+25),2)
        pygame.draw.circle(self.screen,(239,192,151),(x+17,y+11),12)
        pygame.draw.arc(self.screen,(48,40,54),(x+5,y-1,25,21),math.pi,math.tau,5)
        eye_x=x+22 if self.player.facing>0 else x+11
        pygame.draw.circle(self.screen,(27,39,55),(eye_x,y+11),2)
        pygame.draw.circle(self.screen,(255,221,193),(eye_x-1,y+10),1)
        foot=int(math.sin(self.player.anim)*2) if abs(self.player.vx)>0 else 0
        pygame.draw.rect(self.screen,(225,179,105),(x+5,y+42,11,6+foot),border_radius=3); pygame.draw.rect(self.screen,(225,179,105),(x+19,y+42,11,6-foot),border_radius=3)

    def draw(self):
        data=LEVELS[self.level_index]; self.draw_background(data)
        for c in self.coins_world:
            x=c.centerx-self.camera; pulse=int(2*math.sin(pygame.time.get_ticks()/140))
            pygame.draw.ellipse(self.screen,(115,82,45),(x-10,c.y-pulse-2,20,26+2*pulse))
            pygame.draw.ellipse(self.screen,GOLD,(x-8,c.y-pulse,16,22+2*pulse))
            pygame.draw.ellipse(self.screen,(255,244,187),(x-3,c.y+4-pulse,5,13))
        for r,d,t,*_ in self.enemies:
            x=r.x-self.camera; bob=round(math.sin(t*5)*2)
            pygame.draw.ellipse(self.screen,(13,20,34),(x-3,r.bottom-5,40,8))
            pygame.draw.ellipse(self.screen,(124,79,109),(x,r.y+9+bob,34,36))
            pygame.draw.circle(self.screen,(202,114,143),(x+17,r.y+19+bob),14)
            pygame.draw.polygon(self.screen,(222,144,158),[(x+5,r.y+10+bob),(x+7,r.y-1+bob),(x+14,r.y+9+bob)])
            pygame.draw.polygon(self.screen,(222,144,158),[(x+20,r.y+9+bob),(x+28,r.y-1+bob),(x+29,r.y+12+bob)])
            pygame.draw.circle(self.screen,WHITE,(x+11,r.y+18+bob),4); pygame.draw.circle(self.screen,WHITE,(x+23,r.y+18+bob),4)
            pygame.draw.circle(self.screen,(35,32,55),(x+12,r.y+18+bob),2); pygame.draw.circle(self.screen,(35,32,55),(x+24,r.y+18+bob),2)
        # Boss has a clear silhouette and glowing eyes.
        bx=self.boss.x-self.camera
        accent=data["accent"]; pulse=int(5+3*math.sin(pygame.time.get_ticks()/180))
        boss_body=((72,38,78),(91,43,48),(48,57,91))[self.level_index]
        boss_core=((179,77,112),(205,91,74),(104,133,192))[self.level_index]
        pygame.draw.ellipse(self.screen,tuple(channel//5 for channel in accent),(bx-9,self.boss.y+10,self.boss.w+18,self.boss.h-1))
        pygame.draw.ellipse(self.screen,boss_body,(bx,self.boss.y+17,self.boss.w,self.boss.h-17))
        if self.level_index==2:
            pygame.draw.polygon(self.screen,(105,67,112),[(bx+5,self.boss.y+42),(bx+10,self.boss.y-6),(bx+31,self.boss.y+26)])
            pygame.draw.polygon(self.screen,(105,67,112),[(bx+self.boss.w-5,self.boss.y+42),(bx+self.boss.w-10,self.boss.y-6),(bx+self.boss.w-31,self.boss.y+26)])
            pygame.draw.polygon(self.screen,(137,91,145),[(bx+38,self.boss.y-12),(bx+27,self.boss.y+27),(bx+49,self.boss.y+27)])
        elif self.level_index==1:
            pygame.draw.polygon(self.screen,(143,68,63),[(bx+4,self.boss.y+43),(bx-9,self.boss.y+5),(bx+24,self.boss.y+28)])
            pygame.draw.polygon(self.screen,(143,68,63),[(bx+self.boss.w-4,self.boss.y+43),(bx+self.boss.w+9,self.boss.y+5),(bx+self.boss.w-24,self.boss.y+28)])
            pygame.draw.polygon(self.screen,(173,78,68),[(bx+23,self.boss.y+28),(bx+38,self.boss.y-10),(bx+50,self.boss.y+28)])
        else:
            pygame.draw.polygon(self.screen,(122,54,86),[(bx+3,self.boss.y+38),(bx-10,self.boss.y+4),(bx+24,self.boss.y+25)])
            pygame.draw.polygon(self.screen,(122,54,86),[(bx+self.boss.w-3,self.boss.y+38),(bx+self.boss.w+10,self.boss.y+4),(bx+self.boss.w-24,self.boss.y+25)])
        pygame.draw.ellipse(self.screen,boss_core,(bx+14,self.boss.y+26,48,40))
        pygame.draw.circle(self.screen,(255,229,123),(bx+30,self.boss.y+43),pulse)
        pygame.draw.circle(self.screen,(255,229,123),(bx+49,self.boss.y+43),pulse)
        pygame.draw.circle(self.screen,(255,255,220),(bx+30,self.boss.y+43),2)
        pygame.draw.circle(self.screen,(255,255,220),(bx+49,self.boss.y+43),2)
        if self.boss_hp>0:
            pygame.draw.rect(self.screen,(18,18,31),(bx+1,self.boss.y-16,self.boss.w-2,11),border_radius=5)
            pygame.draw.rect(self.screen,(36,27,44),(bx+4,self.boss.y-14,self.boss.w-8,7),border_radius=4)
            pygame.draw.rect(self.screen,RED,(bx+4,self.boss.y-14,int((self.boss.w-8)*self.boss_hp/self.boss_max),7),border_radius=4)
        if self.boss_active and self.boss_hp>0 and self.boss_cool<.35:
            self.text("!",self.large,GOLD,(bx+self.boss.w//2,self.boss.y-35))
        for shot,_,_ in self.boss_projectiles:
            pygame.draw.ellipse(self.screen,(255,125,84),shot.move(-self.camera,0)); pygame.draw.circle(self.screen,(255,225,132),(shot.centerx-self.camera,shot.centery),4)
        self.draw_character(self.player.rect)
        for x,y,vx,vy,life,color in self.particles:pygame.draw.circle(self.screen,color,(int(x-self.camera),int(y)),max(1,int(life*7)))
        self.draw_hud(data)
        if self.state!="PLAYING" and self.state!="BOSS_FIGHT":self.draw_overlay()
        if self.damage_flash>0:
            pygame.draw.rect(self.screen,(206,71,89),(8,8,WIDTH-16,HEIGHT-16),width=4,border_radius=12)
        self.present()

    def draw_hud(self,data):
        pygame.draw.rect(self.screen,(8,15,28),(0,0,WIDTH,72)); pygame.draw.line(self.screen,data["accent"],(0,70),(WIDTH,70),2)
        self.text(f"{self.level_index+1} / 3",self.font,data["accent"],(48,30)); self.text(data["name"],self.font,WHITE,(190,30))
        self.text(f"COINS  {self.coins:02d}",self.font,GOLD,(425,30)); self.text("HP",self.small,MUTED,(585,30))
        for i in range(3):
            color=RED if i<self.player.hp else (67,72,88)
            pygame.draw.circle(self.screen,(20,24,39),(617+i*24,30),10)
            pygame.draw.circle(self.screen,color,(617+i*24,30),7)
        if self.boss_active and self.boss_hp>0:
            self.text("GUARDIAN",self.small,(255,151,150),(795,20))
            pygame.draw.rect(self.screen,(37,29,43),(850,14,130,13),border_radius=6)
            pygame.draw.rect(self.screen,RED,(850,14,int(130*self.boss_hp/self.boss_max),13),border_radius=6)
            self.text(f"{self.boss_hp}/{self.boss_max}",self.small,WHITE,(915,48))
        self.text(self.link.status,self.small,MUTED,(WIDTH//2,HEIGHT-17))

    def draw_overlay(self):
        self.screen.blit(self.overlay_veil,(0,0))
        card=pygame.Rect(140,112,720,416)
        pygame.draw.rect(self.screen,(8,16,29),card,border_radius=22)
        pygame.draw.rect(self.screen,(63,91,113),card,width=2,border_radius=22)
        pygame.draw.line(self.screen,LEVELS[self.level_index]["accent"],(card.left+34,card.top+14),(card.right-34,card.top+14),3)
        if self.state=="MENU":
            self.text(GAME_NAME.upper(),self.title,WHITE,(WIDTH//2,183))
            self.text("Three realms. Three guardians. One journey.",self.font,LEVELS[0]["accent"],(WIDTH//2,235))
            self.text("ARROWS / A D  MOVE",self.font,WHITE,(WIDTH//2,315))
            self.text("UP / W / SPACE  JUMP",self.font,WHITE,(WIDTH//2,350))
            self.text("Land on foes to defeat them. Watch for hazards and boss attacks.",self.small,MUTED,(WIDTH//2,397))
            self.text("ENTER TO BEGIN",self.large,GOLD,(WIDTH//2,455))
            self.text("ESC TO QUIT   ·   F11 FULLSCREEN",self.small,MUTED,(WIDTH//2,495))
        elif self.state=="LEVEL_CLEAR":
            self.text("GUARDIAN DEFEATED",self.large,GOLD,(WIDTH//2,230)); self.text(f"WORLD {self.level_index+1}  ·  {LEVELS[self.level_index]['name']}",self.font,LEVELS[self.level_index]["accent"],(WIDTH//2,286)); self.text(f"Coins collected: {self.coins}",self.font,WHITE,(WIDTH//2,345)); self.text("ENTER  —  NEXT WORLD" if self.level_index<2 else "ENTER  —  FINAL VICTORY",self.font,GOLD,(WIDTH//2,420))
        elif self.state=="PLAYER_DEAD":
            self.text("JOURNEY ENDED",self.large,RED,(WIDTH//2,240)); self.text("The world will remember your next attempt.",self.font,WHITE,(WIDTH//2,310)); self.text("ENTER TO RESTART FROM THE GROVE",self.font,GOLD,(WIDTH//2,380)); self.text(f"Run coins: {self.coins}",self.small,MUTED,(WIDTH//2,430))
        elif self.state=="GAME_FINISHED":
            self.text("GAME FINISHED",self.title,GOLD,(WIDTH//2,230)); self.text("All three guardians have fallen.",self.font,WHITE,(WIDTH//2,305)); self.text(f"Coins gathered: {self.coins}",self.font,LEVELS[2]["accent"],(WIDTH//2,355)); self.text("ENTER TO PLAY AGAIN",self.font,GOLD,(WIDTH//2,425))

    def handle_key(self,key):
        if key==pygame.K_ESCAPE:return False
        if key==pygame.K_RETURN:
            if self.state=="MENU":self.start_game()
            elif self.state=="PLAYER_DEAD":self.start_game()
            elif self.state=="LEVEL_CLEAR":
                if self.level_index<2:self.load_level(self.level_index+1)
                else:self.enter_state("GAME_FINISHED","WIN")
            elif self.state=="GAME_FINISHED":self.start_game()
        return True

    def run(self):
        running=True
        while running:
            dt=min(self.clock.tick(FPS)/1000,0.04); keys=pygame.key.get_pressed()
            for event in pygame.event.get():
                if event.type==pygame.QUIT:running=False
                elif event.type==pygame.VIDEORESIZE and not self.fullscreen:
                    self.windowed_size=(max(MIN_WINDOW_SIZE[0],event.w),max(MIN_WINDOW_SIZE[1],event.h))
                    self.window=pygame.display.set_mode(self.windowed_size,pygame.RESIZABLE)
                elif event.type==pygame.KEYDOWN:
                    if event.key==pygame.K_F11:self.toggle_fullscreen()
                    else:running=self.handle_key(event.key)
            self.update(dt,keys); self.draw()
        self.link.close(); pygame.quit()


def main():
    parser=argparse.ArgumentParser(description="Wayfarer Arduino platformer")
    parser.add_argument("--port",help="Arduino serial port, e.g. COM3")
    parser.add_argument("--keyboard-only",action="store_true",help="start without opening any serial port")
    args=parser.parse_args(); link=ArduinoLink(args.port,args.keyboard_only)
    try:Platformer(link).run()
    except Exception:link.close(); pygame.quit(); raise

if __name__=="__main__":main()
